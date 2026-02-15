from google.cloud import firestore
from app.core.config import settings

# Global Firestore client
_db = None

def get_db():
    global _db
    if _db is None:
        try:
            _db = firestore.Client(
                project=settings.PROJECT_ID,
                database=settings.FIRESTORE_DB
            )
        except Exception as e:
            print(f"Warning: Could not initialize Firestore Client. {e}")
            _db = None
    return _db
