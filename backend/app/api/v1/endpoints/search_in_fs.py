import json
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from app.services.search import SearchService
from app.services.gemini import APILimitExceededError


router = APIRouter()


class SearchRequest(BaseModel):
    """Search request model."""
    municipality: str
    domain: str
    purpose: Optional[str] = ""
    chat_context: Optional[Dict[str, Any]] = None


class ProfilingQuestionsRequest(BaseModel):
    """Profiling questions request model."""
    municipality: str
    domain: str
    purpose: str


@router.post("/search")
async def search(request: SearchRequest):
    """
    Search for government procedures and programs.
    """
    try:
        service = SearchService()
        
        # リクエストデータを構築
        form_data = {
            "municipality": request.municipality,
            "domain": request.domain,
            "purpose": request.purpose or ""
        }
        
        # Add inputs from chat context if available
        if request.chat_context and "inputs" in request.chat_context:
            form_data["inputs"] = request.chat_context["inputs"]
        
        # Step 1: Parse input through Gemini
        parsed_input = service.input_through_gemini(form_data)
        
        # Step 2: Search in Firestore
        search_results = service.search_in_firestore(
            municipality_id=parsed_input.get("municipality_id", ""),
            domain=parsed_input.get("domain", ""),
            life_event_tags=parsed_input.get("life_event_tags", []),
            limit=5
        )
        
        # Step 3: Clean output through Gemini
        if search_results:
            cleaned_output = service.output_through_gemini(
                json.dumps(search_results, ensure_ascii=False)
            )
            return cleaned_output
        else:
            return {}
        
    except APILimitExceededError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e)
        )
    except Exception as e:
        print(f"Search error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )


@router.post("/profiling-questions")
async def get_profiling_questions(request: ProfilingQuestionsRequest):
    """
    Generate profiling questions based on user's purpose.
    """
    try:
        service = SearchService()
        
        questions = service.generate_profiling_questions(
            municipality=request.municipality,
            domain=request.domain,
            purpose=request.purpose
        )
        
        return questions
        
    except APILimitExceededError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate questions: {str(e)}"
        )