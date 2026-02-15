from app.services.municipality import MunicipalityService
from app.services.catalog import CatalogService
from app.services.recommendation import RecommendationEngine
from app.services.adk_assistant import (
    AdkAssistantService,
    get_adk_assistant_service_singleton,
)

def get_municipality_service() -> MunicipalityService:
    return MunicipalityService()

def get_catalog_service() -> CatalogService:
    return CatalogService()

def get_recommendation_engine() -> RecommendationEngine:
    return RecommendationEngine(get_catalog_service())


def get_adk_assistant_service() -> AdkAssistantService:
    return get_adk_assistant_service_singleton()
