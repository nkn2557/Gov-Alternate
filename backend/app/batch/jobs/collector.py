import hashlib
from urllib.parse import urlparse
from datetime import datetime
from app.core.database import get_db
from app.core.config import settings
from app.models.batch import UrlCandidate, BatchStage
from app.models.catalog import Catalog, CatalogStatus
from app.services.search import SearchService
from app.batch.jobs.base import BaseJob, logger

class CollectorJob(BaseJob):
    def __init__(self):
        super().__init__()
        self.db = get_db()
        self.search_service = SearchService()

    def _generate_queries(self, domain: str) -> list[str]:
        if domain == "moving":
            return [
                "転入届",
                "転出届",
                "転居届",
                "世帯変更",
                "マイナンバーカード (申請 or 再交付 or 住所変更)",
                "印鑑登録",
                "健康保険 (転入 or 転出)",
                "(手当 or 給付 or 補助) and (住所変更)",
                "転校",
                "転園",
                "(水道 or 水栓) 引越",
                "ペット 引越",
            ]

        if domain == "childcare":
            return [
                "妊娠 助成",
                "妊娠 給付",
                "妊娠 手当",
                "妊婦 助成",
                "妊婦 給付",
                "妊婦 手当",
                "出生届",
                "出生 助成",
                "出生 給付",
                "出生 手当",
                "出産 助成",
                "出産 給付",
                "出産 手当",
                "出産 休業",
                "産前産後 助成"
                "産前産後 ケア",
                "産前産後 休業",
                "児 助成",
                "児 給付",
                "児 手当",
                "接種 補助"
                "子 医療費 補助",
                "子 医療費 助成",
                "児 保育 助成",
            ]

        return []

    def _normalize_url(self, url: str) -> str:
        # Simple normalization: remove fragment, etc.
        # In production: strict normalization
        try:
            parsed = urlparse(url)
            # Reconstruct without fragment
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        except:
            return url

    async def run(
        self,
        catalog_id: str,
        municipality_id: str,
        municipality_name: str,
        domain: str,
        top_k: int = 5,
        search_engine_ids: list[str] | None = None,
    ):
        logger.info(f"Starting Collector for {municipality_name} ({domain}) -> Catalog {catalog_id}")
        
        # 0. Update Catalog Stage
        self.db.collection(settings.COLLECTION_CATALOGS).document(catalog_id).update({
            "stage": BatchStage.COLLECTING,
            "status": CatalogStatus.BUILDING,
            "updated_at": datetime.now()
        })
        
        # 1. Generate Queries
        queries = self._generate_queries(domain)
        logger.info(f"Generated {len(queries)} queries.")

        total_candidates = 0
        
        # 2. Search & Process
        for q in queries:
            results = self.search_service.execute_search(
                q,
                num=top_k,
                engine_ids=search_engine_ids,
            )
            for res in results:
                url = res["url"]
                url_norm = self._normalize_url(url)
                
                # Check acceptance
                accepted = True
                reason = "Engine filtered"
                
                # Create ID
                candidate_id = hashlib.sha256(url_norm.encode('utf-8')).hexdigest()
                
                candidate = UrlCandidate(
                    id=candidate_id,
                    url=url,
                    url_norm=url_norm,
                    query=q,
                    rank=res["rank"],
                    title=res.get("title"),
                    snippet=res.get("snippet"),
                    host=urlparse(url).netloc,
                    accepted=accepted,
                    reason=reason
                )

                # 3. Upsert Candidate
                # catalog/{id}/url_candidates/{candidate_id}
                self.db.collection(settings.COLLECTION_CATALOGS).document(catalog_id)\
                    .collection("url_candidates").document(candidate_id)\
                    .set(candidate.model_dump())
                    
                total_candidates += 1
        
        # Update stats
        stats = {"candidates_count": total_candidates}
        self.db.collection(settings.COLLECTION_CATALOGS).document(catalog_id).update({
            "stats": stats
        })
        logger.info(f"Collector finished. Candidates: {total_candidates}")
