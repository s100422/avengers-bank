from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.accounts.kinds import AccountType
from avengers_bank.domains.accounts.schemas import (
    AccountCloseRequest,
    AccountCloseResponse,
    AccountHistoryResponse,
    AccountResponse,
    AccountSummaryResponse,
    AccountUpdate,
    CheckingAccountCreate,
    CheckingAccountResponse,
    DepositAccountCreate,
    DepositAccountResponse,
    HistoryFilter,
    SavingsAccountCreate,
    SavingsAccountResponse,
)
from avengers_bank.domains.accounts.service import account_service
from avengers_bank.domains.users.schemas import UserResponse

router = APIRouter(
    prefix="/accounts", tags=["accounts"], responses=error_responses(401, 422)
)

DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]
OPENED = "계좌가 개설되었습니다."


@router.get("", response_model=SuccessResponse[list[AccountSummaryResponse]])
async def list_my_accounts(db: DbSession, user: CurrentUser):
    accounts = await account_service.get_my_accounts(db, user)
    return SuccessResponse[list[AccountSummaryResponse]](data=accounts)


@router.post(
    "/checking",
    response_model=SuccessResponse[CheckingAccountResponse],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 404),
)
async def open_checking(data: CheckingAccountCreate, db: DbSession, user: CurrentUser):
    account = await account_service.open_checking(db, data, user)
    return SuccessResponse[CheckingAccountResponse](data=account, message=OPENED)


@router.post(
    "/deposit",
    response_model=SuccessResponse[DepositAccountResponse],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 404),
)
async def open_deposit(data: DepositAccountCreate, db: DbSession, user: CurrentUser):
    account = await account_service.open_deposit(db, data, user)
    return SuccessResponse[DepositAccountResponse](data=account, message=OPENED)


@router.post(
    "/savings",
    response_model=SuccessResponse[SavingsAccountResponse],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 404),
)
async def open_savings(data: SavingsAccountCreate, db: DbSession, user: CurrentUser):
    account = await account_service.open_savings(db, data, user)
    return SuccessResponse[SavingsAccountResponse](data=account, message=OPENED)


@router.get(
    "/{type}/{account_id}",
    response_model=SuccessResponse[AccountResponse],
    responses=error_responses(404),
)
async def get_account(type: AccountType, account_id: int, db: DbSession, user: CurrentUser):
    account = await account_service.get_account(db, type, account_id, user)
    return SuccessResponse[AccountResponse](data=account)


@router.get(
    "/{type}/{account_id}/histories",
    response_model=SuccessResponse[list[AccountHistoryResponse]],
    responses=error_responses(404),
)
async def get_histories(
    type: AccountType,
    account_id: int,
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    date_from: date | None = None,
    date_to: date | None = None,
    types: Annotated[list[str] | None, Query()] = None,
    min_amount: Annotated[int | None, Query(ge=0)] = None,
    max_amount: Annotated[int | None, Query(ge=0)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
):
    """거래 내역 (최신순). 날짜(KST, 양끝 포함), 거래 종류(여러 개), 금액 범위, 상대 계좌·이름 검색으로 거를 수 있다."""
    f = HistoryFilter(
        date_from=date_from, date_to=date_to, types=types, min_amount=min_amount, max_amount=max_amount, q=q
    )
    histories = await account_service.get_histories(db, type, account_id, user, limit, offset, f)
    return SuccessResponse[list[AccountHistoryResponse]](data=histories)


@router.post(
    "/{type}/{account_id}/close",
    response_model=SuccessResponse[AccountCloseResponse],
    responses=error_responses(400, 404),
)
async def close_account(
    type: AccountType, account_id: int, data: AccountCloseRequest, db: DbSession, user: CurrentUser
):
    result = await account_service.close_account(db, type, account_id, data, user)
    return SuccessResponse[AccountCloseResponse](data=result, message="계좌가 해지되었습니다.")


@router.patch(
    "/{type}/{account_id}",
    response_model=SuccessResponse[AccountResponse],
    responses=error_responses(400, 404),
)
async def update_account(
    type: AccountType, account_id: int, data: AccountUpdate, db: DbSession, user: CurrentUser
):
    account = await account_service.update_account(db, type, account_id, data, user)
    return SuccessResponse[AccountResponse](data=account, message="계좌 정보가 수정되었습니다.")
