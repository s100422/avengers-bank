from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from avengers_bank.core.timezone import today_kst
from avengers_bank.domains.accounts.password import validate_account_password_format
from avengers_bank.domains.terms.schemas import TermsConsentIn

# 입출금 계좌를 개설할 때 한도를 생략하면 쓰는 값 (임시 예시, 팀이 정하면 바꾼다)
DEFAULT_PER_TRANSFER_LIMIT = 1_000_000
DEFAULT_DAILY_TRANSFER_LIMIT = 5_000_000
MAX_AMOUNT = 1_000_000_000_000  # BIGINT 범위를 넘는 값이 DB 오류(500)가 되지 않게 하는 상한

Amount = Annotated[int, Field(gt=0, le=MAX_AMOUNT)]
# 계좌를 만들거나 비밀번호를 정할 때: 숫자 4자리 + 같은 숫자·연속 숫자 금지 (위반이면 422)
NewAccountPassword = Annotated[str, AfterValidator(validate_account_password_format)]
# 돈이 나갈 때 입력하는 값: 형식 검사는 하지 않는다. 틀린 값은 서비스가 실패 횟수로 센다
AccountPassword = Annotated[str, Field(min_length=1, max_length=20)]


def _require_future(value: date) -> date:
    if value <= today_kst():
        raise ValueError("만기일은 오늘보다 뒤여야 합니다.")
    return value


# ── 요청 ──────────────────────────────────────────────────────────────


class CheckingAccountCreate(BaseModel):
    product_id: int
    account_password: NewAccountPassword  # 이 계좌의 비밀번호 (응답에는 절대 넣지 않는다)
    terms: TermsConsentIn  # 화면에서 본 약관 집합과 항목별 동의 (C-075)
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
    account_password: NewAccountPassword  # 이 계좌의 비밀번호 (응답에는 절대 넣지 않는다)
    terms: TermsConsentIn  # 화면에서 본 약관 집합과 항목별 동의 (C-075)
    maturity_date: date
    nickname: str | None = Field(default=None, max_length=50)
    # 가입 금액과 출금할 입출금 계좌는 필수다. 가입 후 추가 입금은 없다.
    initial_amount: Amount
    from_checking_account_id: int
    from_account_password: AccountPassword  # 가입 금액이 나가는 입출금 계좌의 비밀번호

    _maturity = field_validator("maturity_date")(_require_future)


class SavingsAccountCreate(BaseModel):
    product_id: int
    account_password: NewAccountPassword  # 이 계좌의 비밀번호 (응답에는 절대 넣지 않는다)
    terms: TermsConsentIn  # 화면에서 본 약관 집합과 항목별 동의 (C-075)
    monthly_payment: Amount
    monthly_deposit_date: int = Field(ge=1, le=31)
    maturity_date: date
    nickname: str | None = Field(default=None, max_length=50)

    _maturity = field_validator("maturity_date")(_require_future)


class AccountPasswordIn(BaseModel):
    """개발용 API(POST /dev/accounts/.../password)의 본문: 휴대폰 인증 없이 정한다."""

    account_password: NewAccountPassword


class AccountPasswordReset(BaseModel):
    """POST /accounts/{type}/{id}/password: 처음 설정과 재설정(잠금 해제 포함)을 같이 한다."""

    # POST /verification/phone/send-for-me (purpose ACCOUNT_PASSWORD_RESET, 등록 번호로 발송) → verify로 받은 증표
    phone_verification_token: str = Field(min_length=1, max_length=2048, repr=False)
    new_account_password: NewAccountPassword


class AccountUpdate(BaseModel):
    """PATCH: 보낸 필드만 바꾼다. nickname에 null을 보내면 별칭을 지운다. 한도는 입출금 계좌만."""

    nickname: str | None = Field(default=None, max_length=50)
    per_transfer_limit: Amount | None = None
    daily_transfer_limit: Amount | None = None


class HistoryFilter(BaseModel):
    """GET .../histories 검색 조건. 비운 값은 조건에서 뺀다 (C-064)."""

    date_from: date | None = None  # KST 날짜, 그날 포함
    date_to: date | None = None  # KST 날짜, 그날 포함
    types: list[str] | None = None  # 거래 종류 코드 (TRANSFER_OUT, CARD_PAYMENT ...)
    min_amount: int | None = Field(default=None, ge=0)
    max_amount: int | None = Field(default=None, ge=0)
    q: str | None = Field(default=None, max_length=100)  # 상대 계좌번호·이름(사용처) 일부


class AccountCloseRequest(BaseModel):
    """예금·적금 해지: 원금+이자를 받을 내 입출금 계좌 (C-043)"""

    to_checking_account_id: int
    account_password: AccountPassword  # 해지하는 예금·적금 계좌의 비밀번호


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
    password_set: bool  # 계좌 비밀번호를 정했는가 (false면 돈이 나가지 않는다)
    password_locked: bool  # 5회 틀려 잠겼는가 (휴대폰 인증 후 재설정으로 풀린다)

    model_config = ConfigDict(from_attributes=True)


class _AccountResponse(BaseModel):
    account_id: int
    account_num: str
    product_id: int
    balance: int
    nickname: str | None
    created_at: datetime
    password_set: bool  # 계좌 비밀번호를 정했는가
    password_locked: bool  # 5회 틀려 잠겼는가


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
