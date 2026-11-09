from pydantic import BaseModel, ConfigDict, Field

from avengers_bank.domains.accounts.schemas import AccountPassword, Amount


class TransferTarget(BaseModel):
    """이체 내용 (누가·어디로·얼마). AI 이체 초안·확인은 비밀번호 없이 이것만 쓴다 (비밀번호는 따로 확인)."""

    from_checking_account_id: int
    to_account_num: str = Field(min_length=1, max_length=20)
    amount: Amount


class TransferCreate(TransferTarget):
    """POST /transfers — 입출금 → 입출금 이체"""

    account_password: AccountPassword  # 보내는 입출금 계좌의 비밀번호


class SavingsPaymentCreate(BaseModel):
    """POST /transfers/savings — 입출금 → 내 적금 납입"""

    from_checking_account_id: int
    savings_account_id: int
    amount: Amount
    account_password: AccountPassword  # 돈이 나가는 입출금 계좌의 비밀번호


class TransferResponse(BaseModel):
    from_account_num: str
    to_account_num: str
    amount: int
    balance_after: int  # 보낸 입출금 계좌의 거래 후 잔액


class InquiryRequest(BaseModel):
    to_account_num: str = Field(min_length=1, max_length=20)


class InquiryResponse(BaseModel):
    to_account_num: str
    holder_name: str  # 서버가 이미 가린 이름 (홍*동)


class FavoriteCreate(BaseModel):
    bank_code: str = Field(default="", pattern=r"^(\d{3})?$")  # ""은 우리 은행
    bank_name: str = Field(min_length=1, max_length=50)
    account: str = Field(min_length=1, max_length=50)
    name: str | None = Field(default=None, max_length=100)


class FavoriteResponse(FavoriteCreate):
    favorite_id: int

    model_config = ConfigDict(from_attributes=True)


class RecentContact(FavoriteCreate):
    favorite_id: int | None = None  # 자주 쓰는 계좌면 그 id (별이 채워진 상태)
