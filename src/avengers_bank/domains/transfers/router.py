from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.transfers.contacts import contact_service
from avengers_bank.domains.transfers.schemas import (
    FavoriteCreate,
    FavoriteResponse,
    InquiryRequest,
    InquiryResponse,
    RecentContact,
    SavingsPaymentCreate,
    TransferCreate,
    TransferResponse,
)
from avengers_bank.domains.transfers.service import transfer_service
from avengers_bank.domains.users.schemas import UserResponse

router = APIRouter(
    prefix="/transfers", tags=["transfers"], responses=error_responses(401, 422)
)

DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]
FAILURES = error_responses(400, 404)


@router.post(
    "",
    response_model=SuccessResponse[TransferResponse],
    status_code=status.HTTP_201_CREATED,
    responses=FAILURES,
)
async def transfer(data: TransferCreate, db: DbSession, user: CurrentUser):
    result = await transfer_service.transfer(db, data, user)
    return SuccessResponse[TransferResponse](data=result, message="이체가 완료되었습니다.")


@router.post(
    "/savings",
    response_model=SuccessResponse[TransferResponse],
    status_code=status.HTTP_201_CREATED,
    responses=FAILURES,
)
async def pay_savings(data: SavingsPaymentCreate, db: DbSession, user: CurrentUser):
    result = await transfer_service.pay_savings(db, data, user)
    return SuccessResponse[TransferResponse](data=result, message="적금 납입이 완료되었습니다.")


@router.post("/inquiry", response_model=SuccessResponse[InquiryResponse], responses=error_responses(404))
async def inquiry(data: InquiryRequest, db: DbSession, _: CurrentUser):
    """우리 은행 계좌의 받는 분 이름(가림). 이체 화면의 '확인' 단계용."""
    account_num, name = await contact_service.inquiry(db, data.to_account_num)
    return SuccessResponse[InquiryResponse](data=InquiryResponse(to_account_num=account_num, holder_name=name))


@router.get("/recent", response_model=SuccessResponse[list[RecentContact]])
async def recent(db: DbSession, user: CurrentUser):
    return SuccessResponse[list[RecentContact]](data=await contact_service.recent(db, user))


@router.get("/favorites", response_model=SuccessResponse[list[FavoriteResponse]])
async def favorites(db: DbSession, user: CurrentUser):
    return SuccessResponse[list[FavoriteResponse]](data=await contact_service.favorites(db, user))


@router.post(
    "/favorites", response_model=SuccessResponse[FavoriteResponse], status_code=status.HTTP_201_CREATED
)
async def add_favorite(data: FavoriteCreate, db: DbSession, user: CurrentUser):
    return SuccessResponse[FavoriteResponse](data=await contact_service.add_favorite(db, data, user))


@router.delete("/favorites/{favorite_id}", response_model=SuccessResponse[None], responses=error_responses(404))
async def remove_favorite(favorite_id: int, db: DbSession, user: CurrentUser):
    await contact_service.remove_favorite(db, favorite_id, user)
    return SuccessResponse[None](data=None, message="자주 쓰는 계좌에서 뺐습니다.")
