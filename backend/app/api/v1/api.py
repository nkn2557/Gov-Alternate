from fastapi import APIRouter
from app.api.v1.endpoints import (
    assistant,
    municipalities,
    programs,
    recommendations,
    exports,
    search_in_fs,
)

api_router = APIRouter()

api_router.include_router(assistant.router, prefix="/assistant", tags=["assistant"])
api_router.include_router(municipalities.router, prefix="/municipalities", tags=["municipalities"])
api_router.include_router(programs.router, prefix="/programs", tags=["programs"])
api_router.include_router(recommendations.router, prefix="/recommendations", tags=["recommendations"])
api_router.include_router(exports.router, prefix="/exports", tags=["exports"])
api_router.include_router(search_in_fs.router, prefix="/search-fs", tags=["search-firestore"])