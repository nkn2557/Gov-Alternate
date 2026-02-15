import uuid
from datetime import datetime
from app.core.database import get_db
from app.core.config import settings
from app.models.catalog import Catalog, CatalogStatus

class CatalogBuilder:
    def __init__(self):
        self.db = get_db()

    async def start_build(self, municipality_id: str, domain: str) -> str:
        # 1. Create Catalog ID
        catalog_id = str(uuid.uuid4())
        
        # 2. Create Catalog document
        catalog = Catalog(
            id=catalog_id,
            municipality_id=municipality_id,
            domain=domain,
            status=CatalogStatus.BUILDING,
            build_started_at=datetime.now(datetime.UTC)
        )
        
        if self.db:
            self.db.collection(settings.COLLECTION_CATALOGS).document(catalog_id).set(catalog.model_dump())
            
        # 3. Trigger Async Build (Mock for MVP)
        # In real world: PubSub message or Cloud Run Job
        # Here we just leave it as BUILDING or immediately set to READY with mock data if we wanted.
        
        return catalog_id

    async def get_status(self, catalog_id: str) -> Catalog:
        if not self.db:
            return Catalog(
                id=catalog_id, municipality_id="mock", domain="mock",
                status=CatalogStatus.BUILDING, build_started_at=datetime.now(datetime.UTC)
            )
            
        doc = self.db.collection(settings.COLLECTION_CATALOGS).document(catalog_id).get()
        if doc.exists:
            return Catalog(**doc.to_dict())
        return None
