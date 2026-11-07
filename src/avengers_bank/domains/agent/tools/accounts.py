from datetime import date

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.accounts.kinds import KINDS
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.agent.tools.common import ToolArgs, account_name, mask_num
from avengers_bank.domains.users.schemas import UserResponse


class NoArgs(ToolArgs):
    pass


class AccountItem(BaseModel):
    account_type: str  # checking / deposit / savings
    account_id: int  # account_type과 함께 계좌를 가리킨다
    name: str
    account_num_masked: str
    balance: int
    maturity_date: date | None  # 예금·적금만
    status: str


class AccountsResult(BaseModel):
    accounts: list[AccountItem]


async def list_active_accounts(db: AsyncSession, user: UserResponse) -> list[AccountItem]:
    """로그인 사용자의 해지되지 않은 계좌 (입출금은 해지가 없어 항상 ACTIVE)."""
    items, names = [], {}
    for kind in KINDS.values():
        for a in await account_repository.find_by_user_id(db, kind, user.user_id):
            status = getattr(a, "status", "ACTIVE")
            if status != "ACTIVE":
                continue
            items.append(AccountItem(
                account_type=kind.name, account_id=getattr(a, kind.id_column),
                name=await account_name(db, a, names), account_num_masked=mask_num(a.account_num),
                balance=a.balance, maturity_date=getattr(a, "maturity_date", None), status=status,
            ))
    return items


async def get_my_accounts(db: AsyncSession, user: UserResponse, args: NoArgs) -> AccountsResult:
    return AccountsResult(accounts=await list_active_accounts(db, user))
