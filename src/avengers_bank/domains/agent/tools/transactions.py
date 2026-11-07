from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.accounts.kinds import KINDS
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.accounts.schemas import HistoryFilter
from avengers_bank.domains.accounts.service import account_service
from avengers_bank.domains.agent.tools.common import ToolArgs, as_utc, mask_num, to_kst
from avengers_bank.domains.users.schemas import UserResponse

DEFAULT_LIMIT = 20
MAX_LIMIT = 50  # 모델에 한 번에 넘기는 거래 수 상한 (개인정보 최소화)

HistoryType = Literal[
    "TRANSFER_OUT", "TRANSFER_IN", "TO_SAVINGS", "TO_DEPOSIT", "CARD_PAYMENT", "CARD_BILL_PAYMENT",
    "DEV_CHARGE", "CLOSE_IN", "INTEREST", "CLOSE_OUT",
]


class HistoryArgs(ToolArgs):
    account_type: Literal["checking", "deposit", "savings"] | None = Field(default=None, description="계좌 종류")
    account_id: int | None = Field(default=None, description="get_my_accounts의 account_id. account_type과 함께 보낸다")
    date_from: date | None = Field(default=None, description="시작일(KST, 포함) YYYY-MM-DD")
    date_to: date | None = Field(default=None, description="종료일(KST, 포함) YYYY-MM-DD")
    types: list[HistoryType] | None = Field(default=None, description="거래 유형 코드")
    counterpart_name: str | None = Field(default=None, max_length=50, description="상대방 이름·사용처 일부")
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="최대 조회 개수")

    @model_validator(mode="after")
    def _id_needs_type(self):
        if self.account_id is not None and self.account_type is None:
            raise ValueError("account_id를 쓰려면 account_type도 보내야 합니다.")
        return self


class HistoryItem(BaseModel):
    date: datetime  # KST
    account_type: str
    account_num_masked: str
    type: str
    amount: int  # 항상 양수, 입금/출금은 type으로 구분
    balance_after: int
    counterpart_account_masked: str | None
    counterpart_name: str | None


class HistoryResult(BaseModel):
    transactions: list[HistoryItem]
    has_more: bool  # 조건에 맞는 거래가 limit보다 많을 수 있음


async def get_transaction_history(db: AsyncSession, user: UserResponse, args: HistoryArgs) -> HistoryResult:
    if args.account_id is not None:
        # 남의 계좌면 get_owned가 ACCOUNT_NOT_FOUND(404)를 낸다
        kind = KINDS[args.account_type]
        targets = [(kind, await account_service.get_owned(db, kind, args.account_id, user))]
    else:
        kinds = [KINDS[args.account_type]] if args.account_type else list(KINDS.values())
        targets = [(k, a) for k in kinds for a in await account_repository.find_by_user_id(db, k, user.user_id)]

    f = HistoryFilter(date_from=args.date_from, date_to=args.date_to, types=args.types, q=args.counterpart_name)
    rows = []
    for kind, account in targets:
        # 계좌마다 limit+1개씩 받아 합친 뒤 최신순으로 자른다 (소유권은 get_histories가 다시 확인)
        for h in await account_service.get_histories(
            db, kind.name, getattr(account, kind.id_column), user, args.limit + 1, 0, f
        ):
            rows.append(HistoryItem(
                date=to_kst(h.date), account_type=kind.name, account_num_masked=mask_num(account.account_num),
                type=h.type, amount=h.amount, balance_after=h.balance_after,
                counterpart_account_masked=mask_num(h.counterpart_account), counterpart_name=h.counterpart_name,
            ))
    rows.sort(key=lambda r: as_utc(r.date), reverse=True)
    return HistoryResult(transactions=rows[: args.limit], has_more=len(rows) > args.limit)
