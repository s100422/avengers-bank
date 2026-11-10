from uuid import UUID

from pydantic import BaseModel, Field

from avengers_bank.domains.accounts.schemas import AccountPassword, Amount


class BankInfo(BaseModel):
    bank_code: str
    name: str


class InquiryRequest(BaseModel):
    to_bank: str = Field(pattern=r"^\d{3}$")
    to_account: str = Field(min_length=1, max_length=50)


class InquiryResponse(InquiryRequest):
    holder_name: str


class InterbankSend(InquiryRequest):
    """POST /interbank-transfers — 입출금 → 타행 계좌"""

    from_checking_account_id: int
    amount: Amount
    account_password: AccountPassword
    memo: str = Field(default="", max_length=100)
    request_id: UUID | None = None  # 기존 클라이언트 호환. 새 클라이언트는 재시도에도 같은 ID를 보낸다.


class InterbankResponse(BaseModel):
    transfer_id: str
    status: str  # COMPLETED / PENDING(결과 확인 중) / FAILED(조회에서만. 요청에서는 오류 응답)
    to_bank: str
    to_bank_name: str | None
    to_account: str
    amount: int
    holder_name: str | None
    balance_after: int  # 보낸 입출금 계좌의 지금 잔액
    fail_code: str | None = None
    fail_message: str | None = None
