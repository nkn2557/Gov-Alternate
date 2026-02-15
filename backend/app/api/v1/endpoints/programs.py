from typing import List
from fastapi import APIRouter, Depends, Query
from app.models.program import Program
from app.services.catalog import CatalogService
from app.api import deps

router = APIRouter()

@router.get("", response_model=List[Program])
async def list_programs(
    municipality_id: str,
    domain: str,
    service: CatalogService = Depends(deps.get_catalog_service)
):
    programs = await service.get_latest_programs(municipality_id, domain)
    return programs
