from fastapi import APIRouter
from app.api.admin.endpoints import catalog

api_router = APIRouter()
api_router.include_router(catalog.router, prefix="/catalog", tags=["catalog"])
