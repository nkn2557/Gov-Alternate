from datetime import datetime
from app.core.database import get_db
from app.core.config import settings
from app.models.batch import Cluster, BatchStage
from app.models.catalog import Catalog, CatalogStatus
from app.models.program import (
    Program,
    Contact,
    Deadline,
    Source,
    ProgramKind,
    ProgramAction,
    ProgramImportance,
    ProgramEligibility,
)
from app.batch.jobs.base import BaseJob, logger
from app.batch.crawler import WebCrawler
from app.services.extractor import LLMExtractor

class StructurerJob(BaseJob):
    def __init__(self):
        super().__init__()
        self.db = get_db()
        self.crawler = WebCrawler()
        self.extractor = LLMExtractor()

    async def run(self, catalog_id: str, municipality_id: str, domain: str):
        logger.info(f"Starting Structurer for Catalog {catalog_id}")
        
        # 0. Update Stage
        self.db.collection(settings.COLLECTION_CATALOGS).document(catalog_id).update({
            "stage": BatchStage.STRUCTURING
        })

        # 1. Read Clusters
        clusters_ref = self.db.collection(settings.COLLECTION_CATALOGS).document(catalog_id)\
            .collection("clusters")
            
        programs_count = 0
        
        for doc in clusters_ref.get():
            cluster = Cluster(**doc.to_dict())
            logger.info(f"Processing cluster {cluster.id} ({cluster.primary_url})")
            
            # 2. Fetch Primary Content (HTML or PDF)
            force_pdf = cluster.primary_url.lower().endswith(".pdf")
            content, is_pdf = await self.crawler.fetch_content(cluster.primary_url, force_pdf=force_pdf)
            if not content:
                logger.warning(f"Failed to fetch primary url {cluster.primary_url}")
                continue
            if is_pdf or force_pdf:
                logger.info(f"PDF content detected for {cluster.id}")
                
            # 3. Extract
            data = await self.extractor.extract_program_info(content)
            if isinstance(data, list):
                data = next((item for item in data if isinstance(item, dict)), {})
            if not isinstance(data, dict):
                logger.warning(
                    "Extraction returned invalid type for %s: %s",
                    cluster.id,
                    type(data).__name__,
                )
                continue
            if not data or not data.get("title_official"):
                logger.warning(f"Extraction failed/empty for {cluster.id}")
                continue

            # 4. Construct Program
            try:
                raw_prevalence = data.get("need_prevalence_score")
                need_prevalence_score = None
                if raw_prevalence is not None:
                    try:
                        parsed_prevalence = float(raw_prevalence)
                        # Keep normalized 0-100 range for stable ranking.
                        need_prevalence_score = max(0.0, min(100.0, parsed_prevalence))
                    except (TypeError, ValueError):
                        need_prevalence_score = None

                eligibility_profile = data.get("eligibility_profile")
                if isinstance(eligibility_profile, dict):
                    parsed_eligibility = ProgramEligibility(**eligibility_profile)
                else:
                    # Keep structured fields present (null by default) for query-stage filtering.
                    parsed_eligibility = ProgramEligibility()

                # Map fields safely
                program = Program(
                    municipality_id=municipality_id,
                    domain=domain,
                    canonical_key=cluster.id, # KEY = CLUSTER ID
                    title_official=data.get("title_official") or "Unknown",
                    title_common=data.get("title_common") or data.get("title_official"),
                    summary=data.get("summary", ""),
                    steps=data.get("steps") or [],
                    kind=data.get("kind") or ProgramKind.PROCEDURE,
                    actions=data.get("actions") or [],
                    importance=data.get("importance") or ProgramImportance.UNKNOWN,
                    life_event_tags=data.get("life_event_tags") or [],
                    official_urls=cluster.member_urls, # SET MEMBERS
                    contact=Contact(name="役所窓口"), # Mock/Default
                    deadline=Deadline(type="unknown"), 
                    eligibility_text=data.get("eligibility_text") or "",
                    eligibility_profile=parsed_eligibility,
                    need_prevalence_score=need_prevalence_score,
                    required_info=data.get("required_info") or [],
                    source=Source(
                        retrieved_at=datetime.now(),
                        source_title=data.get("title_official")
                    )
                )
                
                # Save
                self.db.collection(settings.COLLECTION_CATALOGS).document(catalog_id)\
                    .collection("programs").document(program.canonical_key)\
                    .set(program.model_dump())
                    
                programs_count += 1
                
            except Exception as e:
                logger.error(f"Validation Error for {cluster.id}: {e}")
                
        # 5. Finalize
        self.db.collection(settings.COLLECTION_CATALOGS).document(catalog_id).update({
            "stage": BatchStage.DONE,
            "status": CatalogStatus.READY,
            "build_finished_at": datetime.now(),
            "stats.programs_count": programs_count
        })
        
        # Update Pointer (Success case)
        if programs_count > 0:
            self.db.collection(settings.COLLECTION_CATALOG_POINTERS).document(f"{municipality_id}_{domain}").set({
                "current_catalog_id": catalog_id,
                "updated_at": datetime.now()
            })
            
        logger.info(f"Structurer finished. Programs: {programs_count}")
        await self.crawler.close()
