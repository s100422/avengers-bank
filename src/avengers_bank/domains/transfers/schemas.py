from pydantic import BaseModel, Field

from avengers_bank.domains.accounts.schemas import Amount


class TransferCreate(BaseModel):
    """POST /transfers — 입출금 → 입출금 이체"""

    from_checking_account_id: int
    to_account_num: str = Field(min_length=1, max_length=20)
    amount: Amount


class SavingsPaymentCreate(BaseModel):
    """POST /transfers/savings — 입출금 → 내 적금 납입"""

    from_checking_account_id: int
    savings_account_id: int
    amount: Amount


class DepositPaymentCreate(BaseModel):
    """POST /transfers/deposit — 입출금 → 내 예금 입금"""

    from_checking_account_id: int
    deposit_account_id: int
    amount: Amount


class TransferResponse(BaseModel):
    from_account_num: str
    to_account_num: str
    amount: int
    balance_after: int  # 보낸 입출금 계좌의 거래 후 잔액
