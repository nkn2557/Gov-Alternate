import hashlib
from app.core.database import get_db
from app.core.config import settings
from app.models.batch import UrlCandidate, BatchStage, Cluster, ClusterConfidence
from app.batch.jobs.base import BaseJob, logger
from app.batch.crawler import WebCrawler
from bs4 import BeautifulSoup

class DeduperJob(BaseJob):
    def __init__(self):
        super().__init__()
        self.db = get_db()
        self.crawler = WebCrawler()

    async def _fetch_and_feature(self, candidate: UrlCandidate) -> UrlCandidate:
        # Lightweight fetch
        html = await self.crawler.fetch_page(candidate.url)
        if not html:
            return candidate
            
        soup = BeautifulSoup(html, "html.parser")
        
        # Title Norm
        title = soup.title.string if soup.title else ""
        candidate.title_norm = title.strip() if title else candidate.title
        
        # Text Sig (SimHash placeholder: just use content length or generic hash for MVP)
        # In real impl, use embedding. Here we mock it or use simple hash.
        text_content = soup.get_text()[:600]
        # candidate.text_sig = ... (Skipping complex embedding for MVP)
        
        return candidate

    async def run(self, catalog_id: str, municipality_id: str, domain: str):
        logger.info(f"Starting Deduper for Catalog {catalog_id}")
        
        # 0. Update Stage
        self.db.collection(settings.COLLECTION_CATALOGS).document(catalog_id).update({
            "stage": BatchStage.DEDUPING
        })

        # 1. Read Candidates
        candidates_ref = self.db.collection(settings.COLLECTION_CATALOGS).document(catalog_id)\
            .collection("url_candidates").where("accepted", "==", True)
            
        candidates = []
        for doc in candidates_ref.stream():
            candidates.append(UrlCandidate(**doc.to_dict()))
            
        logger.info(f"Processing {len(candidates)} candidates.")
        
        # 2. Fetch & Feature (loop for MVP, parallelize in Prod)
        enriched_candidates = []
        for c in candidates:
            # We skip fetch if title_norm exists (idempotency check)
            if not c.title_norm:
                c = await self._fetch_and_feature(c)
                # Save back features
                self.db.collection(settings.COLLECTION_CATALOGS).document(catalog_id)\
                    .collection("url_candidates").document(c.id)\
                    .set(c.model_dump())
            enriched_candidates.append(c)
            
        # 3. Clustering (Simple L0: URL Norm exact match)
        # Note: In real world, we do pairwise comparison.
        # MVP: Group by url_norm
        groups = {}
        for c in enriched_candidates:
            key = c.url_norm
            if key not in groups:
                groups[key] = []
            groups[key].append(c)
            
        # Create Clusters
        clusters_count = 0
        for url_norm, members in groups.items():
            primary = members[0] # Pick first rank usually, but here just first
            
            # Cluster ID
            raw_id = f"{municipality_id}{domain}{url_norm}"
            cluster_id = hashlib.sha256(raw_id.encode()).hexdigest()
            
            member_urls = list(set([m.url_norm for m in members]))
            titles = list(set([m.title_norm or m.title for m in members if m.title or m.title_norm]))
            
            cluster = Cluster(
                id=cluster_id,
                primary_url=primary.url,
                member_urls=member_urls,
                titles=titles,
                confidence=ClusterConfidence.HIGH # L0 match
            )
            
            # Save
            self.db.collection(settings.COLLECTION_CATALOGS).document(catalog_id)\
                .collection("clusters").document(cluster_id)\
                .set(cluster.model_dump())
                
            clusters_count += 1
            
        # Update Stats
        # We need to read existing stats first to merge, but Firestore update accepts merge
        self.db.collection(settings.COLLECTION_CATALOGS).document(catalog_id).update({
            "stats.clusters_count": clusters_count
        })
        
        logger.info(f"Deduper finished. Clusters: {clusters_count}")
        await self.crawler.close()
