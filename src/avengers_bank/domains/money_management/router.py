from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.exceptions import ApiException
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.agent.model_client import get_model_client
from avengers_bank.domains.money_management.domain import Category, Source
from avengers_bank.domains.money_management.schemas import (
    CategoryDetailResponse,
    CategoryUpdate,
    OneOffUpdate,
    RecurringCreate,
    RecurringDismiss,
    RecurringItemOut,
    RecurringResponse,
    RecurringUpdate,
    ScheduledItem,
    SummaryResponse,
    TxnDetailResponse,
)
from avengers_bank.domains.money_management.service import money_service, parse_month
from avengers_bank.domains.users.schemas import UserResponse

router = APIRouter(prefix="/money", tags=["money"], responses=error_responses(401, 422))

DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]
Month = Annotated[str | None, Query(description="YYYY-MM, 비우면 이번 달")]


def optional_model_client():
    """AI 키가 없으면 None: 분류 안 된 가맹점은 미분류로 두고 화면은 그대로 보여준다."""
    try:
        return get_model_client()
    except ApiException:
        return None


Client = Annotated[object | None, Depends(optional_model_client)]


@router.get("/summary", response_model=SuccessResponse[SummaryResponse], responses=error_responses(400))
async def summary(db: DbSession, user: CurrentUser, client: Client, month: Month = None):
    return SuccessResponse[SummaryResponse](data=await money_service.summary(db, user, parse_month(month), client))


@router.get("/schedule", response_model=SuccessResponse[list[ScheduledItem]], responses=error_responses(400))
async def schedule(db: DbSession, user: CurrentUser, month: Month = None):
    return SuccessResponse[list[ScheduledItem]](data=await money_service.schedule(db, user, parse_month(month)))


@router.get("/categories/{category}", response_model=SuccessResponse[CategoryDetailResponse], responses=error_responses(400))
async def category_detail(category: Category, db: DbSession, user: CurrentUser, client: Client, month: Month = None):
    data = await money_service.category(db, user, category, parse_month(month), client)
    return SuccessResponse[CategoryDetailResponse](data=data)


@router.get("/transactions/{source}/{source_id}", response_model=SuccessResponse[TxnDetailResponse], responses=error_responses(404))
async def transaction(source: Source, source_id: int, db: DbSession, user: CurrentUser, client: Client):
    return SuccessResponse[TxnDetailResponse](data=await money_service.transaction(db, user, source, source_id, client))


@router.put("/transactions/{source}/{source_id}/category", response_model=SuccessResponse[TxnDetailResponse], responses=error_responses(400, 404))
async def set_category(source: Source, source_id: int, body: CategoryUpdate, db: DbSession, user: CurrentUser):
    data = await money_service.set_category(db, user, source, source_id, body)
    return SuccessResponse[TxnDetailResponse](data=data, message="분류를 바꿨습니다.")


@router.put("/transactions/{source}/{source_id}/one-off", response_model=SuccessResponse[TxnDetailResponse], responses=error_responses(404))
async def set_one_off(source: Source, source_id: int, body: OneOffUpdate, db: DbSession, user: CurrentUser):
    data = await money_service.set_one_off(db, user, source, source_id, body.is_one_off)
    return SuccessResponse[TxnDetailResponse](data=data)


@router.get("/recurring", response_model=SuccessResponse[RecurringResponse])
async def list_recurring(db: DbSession, user: CurrentUser, client: Client):
    return SuccessResponse[RecurringResponse](data=await money_service.recurring(db, user, client))


@router.post("/recurring", response_model=SuccessResponse[RecurringItemOut], status_code=201)
async def add_recurring(body: RecurringCreate, db: DbSession, user: CurrentUser):
    data = await money_service.add_recurring(db, user, body)
    return SuccessResponse[RecurringItemOut](data=data, message="정기 거래로 등록했습니다.")


@router.patch("/recurring/{recurring_id}", response_model=SuccessResponse[RecurringItemOut], responses=error_responses(404))
async def update_recurring(recurring_id: int, body: RecurringUpdate, db: DbSession, user: CurrentUser):
    return SuccessResponse[RecurringItemOut](data=await money_service.update_recurring(db, user, recurring_id, body))


@router.post("/recurring/dismiss", response_model=SuccessResponse[None])
async def dismiss_candidate(body: RecurringDismiss, db: DbSession, user: CurrentUser):
    await money_service.dismiss(db, user, body)
    return SuccessResponse[None](data=None, message="반복 거래 후보에서 뺐습니다.")
