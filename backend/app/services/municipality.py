from typing import List, Optional
from app.core.database import get_db
from app.core.config import settings
from app.models.municipality import Municipality

class MunicipalityService:
    def __init__(self):
        self.db = get_db()

    async def search(self, query: str = "") -> List[Municipality]:
        if not self.db:
            # Mock return if DB not connected (for local testing without creds)
            if query == "mock":
                return [Municipality(id="tokyo-chiyoda", name="千代田区")]
            return []

        # Simple prefix search or fetch all and filter (MVP)
        # Assuming low number of municipalities for MVP (3 targets)
        
        # Todo: Indexing for search
        docs = self.db.collection(settings.COLLECTION_MUNICIPALITIES).where("enabled", "==", True).stream()
        
        results = []
        for doc in docs:
            m = Municipality(**doc.to_dict())
            if not query or query in m.name:
                results.append(m)
        
        return results

    async def get_by_id(self, municipality_id: str) -> Optional[Municipality]:
        if not self.db:
            return None
        
        doc = self.db.collection(settings.COLLECTION_MUNICIPALITIES).document(municipality_id).get()
        if doc.exists:
            return Municipality(**doc.to_dict())
        return None
