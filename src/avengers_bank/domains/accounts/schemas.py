from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from avengers_bank.core.timezone import today_kst

# 입출금 계좌를 개설할 때 한도를 생략하면 쓰는 값 (임시 예시, 팀이 정하면 바꾼다)
DEFAULT_PER_TRANSFER_LIMIT = 1_000_000
DEFAULT_DAILY_TRANSFER_LIMIT = 5_000_000
MAX_AMOUNT = 1_000_000_000_000  # BIGINT 범위를 넘는 값이 DB 오류(500)가 되지 않게 하는 상한

Amount = Annotated[int, Field(gt=0, le=MAX_AMOUNT)]


def _require_future(value: date) -> date:
    if value <= today_kst():
        raise ValueError("만기일은 오늘보다 뒤여야 합니다.")
    return value


# ── 요청 ──────────────────────────────────────────────────────────────


class CheckingAccountCreate(BaseModel):
    product_id: int
    nickname: str | None = Field(default=None, max_length=50)
    per_transfer_limit: Amount = DEFAULT_PER_TRANSFER_LIMIT
    daily_transfer_limit: Amount = DEFAULT_DAILY_TRANSFER_LIMIT

    @model_validator(mode="after")
    def _per_not_over_daily(self):
        if self.per_transfer_limit > self.daily_transfer_limit:
            raise ValueError("1회 이체 한도는 1일 이체 한도보다 클 수 없습니다.")
        return self


class DepositAccountCreate(BaseModel):
    product_id: int
    maturity_date: date
    nickname: str | None = Field(default=None, max_length=50)

    _maturity = field_validator("maturity_date")(_require_future)


class SavingsAccountCreate(BaseModel):
    product_id: int
    monthly_payment: Amount
    monthly_deposit_date: int = Field(ge=1, le=31)
    maturity_date: date
    nickname: str | None = Field(default=None, max_length=50)

    _maturity = field_validator("maturity_date")(_require_future)


class AccountUpdate(BaseModel):
    """PATCH: 보낸 필드만 바꾼다. nickname에 null을 보내면 별칭을 지운다. 한도는 입출금 계좌만."""

    nickname: str | None = Field(default=None, max_length=50)
    per_transfer_limit: Amount | None = None
    daily_transfer_limit: Amount | None = None


class AccountCloseRequest(BaseModel):
    """예금·적금 해지: 원금+이자를 받을 내 입출금 계좌 (C-043)"""

    to_checking_account_id: int


# ── 응답 ──────────────────────────────────────────────────────────────


class AccountSummaryResponse(BaseModel):
    """GET /accounts — 3종 계좌를 한 목록으로 보여줄 때 쓰는 공통 모양"""

    account_type: str  # checking / deposit / savings
    account_id: int
    account_num: str
    balance: int
    nickname: str | None
    created_at: datetime
    status: str | None = None  # 예금·적금만: ACTIVE / CLOSED (입출금은 null)

    model_config = ConfigDict(from_attributes=True)


class _AccountResponse(BaseModel):
    account_id: int
    account_num: str
    product_id: int
    balance: int
    nickname: str | None
    created_at: datetime


class CheckingAccountResponse(_AccountResponse):
    account_type: Literal["checking"] = "checking"
    per_transfer_limit: int
    daily_transfer_limit: int


class DepositAccountResponse(_AccountResponse):
    account_type: Literal["deposit"] = "deposit"
    maturity_date: date
    status: str
    closed_at: datetime | None


class SavingsAccountResponse(_AccountResponse):
    account_type: Literal["savings"] = "savings"
    monthly_payment: int
    monthly_deposit_date: int
    maturity_date: date
    status: str
    closed_at: datetime | None


AccountResponse = Annotated[
    CheckingAccountResponse | DepositAccountResponse | SavingsAccountResponse,
    Field(discriminator="account_type"),
]

RESPONSES = {
    "checking": CheckingAccountResponse,
    "deposit": DepositAccountResponse,
    "savings": SavingsAccountResponse,
}


class AccountCloseResponse(BaseModel):
    account_type: str
    account_id: int
    principal: int  # 해지 전 잔액
    interest: int
    total_amount: int  # principal + interest, 입출금 계좌로 들어간 금액
    early_close: bool  # 만기 전 중도 해지 (이자가 금리의 절반)
    closed_at: datetime
    to_account_num: str
    to_balance_after: int


class AccountHistoryResponse(BaseModel):
    date: datetime
    amount: int  # 항상 양수, 입금/출금은 type으로 구분
    balance_after: int
    type: str
    counterpart_account: str | None
    counterpart_name: str | None = None

    model_config = ConfigDict(from_attributes=True)
