import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_ID: str = os.getenv("GOOGLE_CLOUD_PROJECT", "gov-alternate")
    CORS_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,"
            "http://localhost:8888,http://127.0.0.1:8888",
        ).split(",")
        if origin.strip()
    ]
    # Firestore - Support named database
    FIRESTORE_DB: str = os.getenv("FIRESTORE_DB", "gov-secretary")

    # Firestore Collections
    COLLECTION_MUNICIPALITIES: str = "municipalities"
    COLLECTION_CATALOGS: str = "catalogs"
    COLLECTION_CATALOG_POINTERS: str = "catalog_pointers"
    # Subcollection name
    COLLECTION_PROGRAMS: str = "programs"
    
    
    # Vertex AI
    GOOGLE_CLOUD_REGION: str = os.getenv("GOOGLE_CLOUD_REGION", "us-central1")
    GEMINI_MODEL_NAME: str = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash")

    # Vertex AI Search (Discovery Engine)
    VERTEX_AI_SEARCH_LOCATION: str = os.getenv("VERTEX_AI_SEARCH_LOCATION", "global")
    VERTEX_AI_SEARCH_COLLECTION: str = os.getenv("VERTEX_AI_SEARCH_COLLECTION", "default_collection")
    VERTEX_AI_SEARCH_SERVING_CONFIG: str = os.getenv("VERTEX_AI_SEARCH_SERVING_CONFIG", "default_search")
    VERTEX_AI_SEARCH_DEFAULT_ENGINE_IDS: str = os.getenv("VERTEX_AI_SEARCH_DEFAULT_ENGINE_IDS", "")
    # Comma-separated map: municipality_id:engine_id,municipality_id2:engine_id2
    VERTEX_AI_SEARCH_ENGINE_IDS: str = os.getenv("VERTEX_AI_SEARCH_ENGINE_IDS", "")
    VERTEX_AI_SEARCH_DEBUG: bool = os.getenv("VERTEX_AI_SEARCH_DEBUG", "false").lower() in ("1", "true", "yes")

    # Catalog Builder / Crawler
    CRAWLER_TIMEOUT_SECONDS: int = 30
    CRAWLER_MAX_RETRIES: int = 3

    # Gemini API settings
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    DAILY_API_LIMIT: int = 1000
    API_COUNTER_COLLECTION: str = "api_usage"

    class Config:
        case_sensitive = True

settings = Settings()
