from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.services.builder import CatalogBuilder

router = APIRouter()

class BuildRequest(BaseModel):
    municipality_id: str
    domain: str

class BuildResponse(BaseModel):
    catalog_id: str
    status: str

@router.post("/build", response_model=BuildResponse)
async def build_catalog(
    request: BuildRequest,
):
    builder = CatalogBuilder()
    catalog_id = await builder.start_build(request.municipality_id, request.domain)
    return BuildResponse(catalog_id=catalog_id, status="building")

@router.get("/{catalog_id}/status")
async def get_catalog_status(catalog_id: str):
    builder = CatalogBuilder()
    catalog = await builder.get_status(catalog_id)
    if not catalog:
        raise HTTPException(status_code=404, detail="Catalog not found")
    return catalog
