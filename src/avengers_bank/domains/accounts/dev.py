"""개발용 API: 입출금 계좌 잔액을 채워서 이체·결제를 시험한다. 기존 계좌(비밀번호 미설정)에 계좌 비밀번호를 정한다.

ENABLE_DEV_ENDPOINTS=true 일 때만 main.py가 등록한다. 운영 환경에서는 켜지 않는다.
지우려면: 이 파일, main.py의 dev 라우터 등록(2줄), config.py의 enable_dev_endpoints를 삭제한다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.accounts.kinds import KINDS, AccountType
from avengers_bank.domains.accounts.models import CheckingAccountHistory
from avengers_bank.domains.accounts.password import set_account_password
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.accounts.schemas import (
    AccountPasswordIn,
    AccountResponse,
    Amount,
    CheckingAccountResponse,
)
from avengers_bank.domains.accounts.service import account_service, to_response
from avengers_bank.domains.users.schemas import UserResponse

router = APIRouter(
    prefix="/dev", tags=["dev (개발용)"], responses=error_responses(401, 422)
)


class ChargeRequest(BaseModel):
    amount: Amount


async def charge_checking(
    db: AsyncSession, account_id: int, amount: int, user: UserResponse
) -> CheckingAccountResponse:
    kind = KINDS["checking"]
    async with db.begin():
        await account_service.get_owned(db, kind, account_id, user)  # 본인 계좌인지 (불변이라 잠금 전에 확인)
        # 규칙 9: 잔액을 바꾸기 전에 잠그고, 잠근 시점의 잔액을 쓴다
        (account,) = await account_repository.lock_checking_accounts(db, [account_id])
        account.balance += amount
        await account_repository.save_history(
            db,
            CheckingAccountHistory(
                checking_account_id=account_id, amount=amount,
                balance_after=account.balance, type="DEV_CHARGE",
            ),
        )
    return to_response(kind, account)


@router.post(
    "/accounts/checking/{account_id}/charge",
    response_model=SuccessResponse[CheckingAccountResponse],
    responses=error_responses(404),
)
async def charge(
    account_id: int,
    data: ChargeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[UserResponse, Depends(get_current_user)],
):
    account = await charge_checking(db, account_id, data.amount, user)
    return SuccessResponse[CheckingAccountResponse](data=account, message="개발용 충전이 완료되었습니다.")


@router.post(
    "/accounts/{type}/{account_id}/password",
    response_model=SuccessResponse[AccountResponse],
    responses=error_responses(404),
)
async def set_password(
    type: AccountType,
    account_id: int,
    data: AccountPasswordIn,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[UserResponse, Depends(get_current_user)],
):
    """개발용: 휴대폰 인증 없이 내 계좌 비밀번호를 정한다(잠금도 풀린다). 운영용 설정·재설정 API는 휴대폰 인증이 필요해 2단계에서 만든다."""
    kind = KINDS[type]
    async with db.begin():
        await account_service.get_owned(db, kind, account_id, user)  # 남의 계좌는 404
        account = await account_repository.lock_account(db, kind, account_id)
        await set_account_password(db, account, data.account_password)
    return SuccessResponse[AccountResponse](data=to_response(kind, account), message="계좌 비밀번호를 설정했습니다.")
