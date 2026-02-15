from fastapi import APIRouter, Depends, HTTPException

from app.api import deps
from app.models.api import AssistantChatRequest, AssistantChatResponse
from app.services.adk_assistant import AdkAssistantService

router = APIRouter()


@router.post("/chat", response_model=AssistantChatResponse)
async def chat_with_assistant(
    request: AssistantChatRequest,
    service: AdkAssistantService = Depends(deps.get_adk_assistant_service),
):
    try:
        result = await service.chat(
            municipality=request.municipality,
            domain=request.domain,
            profile=request.profile or {},
            user_message=request.user_message,
            session_id=request.session_id,
            user_id=request.user_id,
            expect_tool_result=request.expect_tool_result,
            request_more=request.request_more,
        )
        return AssistantChatResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"assistant chat failed: {exc}") from exc
