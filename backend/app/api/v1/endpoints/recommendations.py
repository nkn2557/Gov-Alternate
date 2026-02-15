from datetime import datetime
from fastapi import APIRouter, Depends
from app.models.api import RecommendationRequest, RecommendationResponse
from app.services.recommendation import RecommendationEngine
from app.api import deps

router = APIRouter()

@router.post("", response_model=RecommendationResponse)
async def get_recommendations(
    request: RecommendationRequest,
    engine: RecommendationEngine = Depends(deps.get_recommendation_engine)
):
    cards = await engine.recommend(
        request.municipality_id,
        request.category,
        request.profile
    )
    
    return RecommendationResponse(
        cards=cards,
        program_count=len(cards),
        generated_at=datetime.now(datetime.UTC).isoformat()
    )
