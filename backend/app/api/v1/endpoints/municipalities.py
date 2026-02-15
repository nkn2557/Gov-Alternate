from typing import List
from fastapi import APIRouter, Depends
from app.models.api import MunicipalitySearchItem
from app.services.municipality import MunicipalityService
from app.api import deps

router = APIRouter()

@router.get("/search", response_model=List[MunicipalitySearchItem])
async def search_municipalities(
    q: str = "",
    service: MunicipalityService = Depends(deps.get_municipality_service)
):
    results = await service.search(q)
    return [
        MunicipalitySearchItem(municipality_id=m.id, name=m.name)
        for m in results
    ]
