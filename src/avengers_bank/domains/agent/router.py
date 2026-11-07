from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.agent.model_client import ModelClient, get_model_client
from avengers_bank.domains.agent.schemas import (
    ChatRequest,
    ChatResponse,
    DraftCancelResponse,
    DraftConfirmResponse,
)
from avengers_bank.domains.agent.service import agent_service
from avengers_bank.domains.users.schemas import UserResponse

router = APIRouter(prefix="/agent", tags=["agent (AI 금융 비서)"], responses=error_responses(401, 422))

CurrentUser = Annotated[UserResponse, Depends(get_current_user)]
DraftId = Annotated[str, Path(min_length=1, max_length=43)]


@router.post("/chat", response_model=SuccessResponse[ChatResponse], responses=error_responses(404))
async def chat(
    data: ChatRequest, user: CurrentUser, client: Annotated[ModelClient, Depends(get_model_client)]
):
    """AI 금융 비서에게 질문한다. 이체 요청이면 실행하지 않고 action(이체 확인 카드)을 돌려준다."""
    return SuccessResponse[ChatResponse](data=await agent_service.chat(data, user, client))


@router.post(
    "/transfers/{draft_id}/confirm",
    response_model=SuccessResponse[DraftConfirmResponse],
    responses=error_responses(400, 404, 409),
)
async def confirm_transfer(
    draft_id: DraftId, user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
):
    """사용자가 확인 카드에서 '이체하기'를 눌렀을 때만 부른다. 잔액·한도를 다시 검사하고 이체한다."""
    result = await agent_service.confirm_draft(db, draft_id, user)
    return SuccessResponse[DraftConfirmResponse](data=result, message="이체가 완료되었습니다.")


@router.post(
    "/transfers/{draft_id}/cancel",
    response_model=SuccessResponse[DraftCancelResponse],
    responses=error_responses(404, 409),
)
async def cancel_transfer(
    draft_id: DraftId, user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]
):
    result = await agent_service.cancel_draft(db, draft_id, user)
    return SuccessResponse[DraftCancelResponse](data=result, message="이체를 취소했습니다.")
