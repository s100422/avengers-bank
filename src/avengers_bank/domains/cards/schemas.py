from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from avengers_bank.domains.accounts.schemas import Amount

# ── 요청 ──────────────────────────────────────────────────────────────


class CreditCardCreate(BaseModel):
    """신용 한도는 받지 않는다. 상품(card_products)의 한도가 그대로 복사된다 (C-013)."""

    product_id: int
    checking_account_id: int  # 결제 계좌
    payment_date: int = Field(ge=1, le=31)  # 매월 결제일


class DebitCardCreate(BaseModel):
    product_id: int
    checking_account_id: int  # 출금 계좌


class CardPaymentCreate(BaseModel):
    place_of_use: str = Field(min_length=1, max_length=100)
    used_amount: Amount


class BillCreate(BaseModel):
    year_month: str = Field(pattern=r"^[1-9]\d{3}-(0[1-9]|1[0-2])$", examples=["2026-10"])


# ── 응답 ──────────────────────────────────────────────────────────────


class CardSummaryResponse(BaseModel):
    """GET /cards — 신용·체크카드를 한 목록으로 보여줄 때 쓰는 공통 모양.

    accumulated_amount의 뜻은 카드마다 다르다: 신용카드는 미결제액, 체크카드는 누적 사용액 (C-012).
    """

    card_type: str  # credit / debit
    card_id: int
    card_num: str
    checking_account_id: int
    accumulated_amount: int

    model_config = ConfigDict(from_attributes=True)


class _CardResponse(BaseModel):
    card_id: int
    card_num: str
    product_id: int
    checking_account_id: int
    accumulated_amount: int


class CreditCardResponse(_CardResponse):
    card_type: Literal["credit"] = "credit"
    credit_limit: int
    payment_date: int


class DebitCardResponse(_CardResponse):
    card_type: Literal["debit"] = "debit"


CardResponse = Annotated[
    CreditCardResponse | DebitCardResponse, Field(discriminator="card_type")
]

RESPONSES = {"credit": CreditCardResponse, "debit": DebitCardResponse}


class CardHistoryResponse(BaseModel):
    place_of_use: str
    used_amount: int
    time: datetime

    model_config = ConfigDict(from_attributes=True)


class CardPaymentResponse(CardHistoryResponse):
    accumulated_amount: int  # 결제 후 값 (신용카드는 미결제액)


class BillResponse(BaseModel):
    bill_id: int
    credit_card_id: int
    period_start: date
    period_end: date
    total_amount: int
    due_date: date
    status: str  # UNPAID / PAID
    paid_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class BillDetailResponse(BillResponse):
    items: list[CardHistoryResponse]  # 이 청구서에 포함된 사용내역
