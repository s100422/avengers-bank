from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.transfers.schemas import (
    DepositPaymentCreate,
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
FAILURES = error_responses(400, 403, 404)


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


@router.post(
    "/deposit",
    response_model=SuccessResponse[TransferResponse],
    status_code=status.HTTP_201_CREATED,
    responses=FAILURES,
)
async def pay_deposit(data: DepositPaymentCreate, db: DbSession, user: CurrentUser):
    result = await transfer_service.pay_deposit(db, data, user)
    return SuccessResponse[TransferResponse](data=result, message="예금 입금이 완료되었습니다.")
