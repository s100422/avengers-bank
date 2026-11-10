from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class AccountProductResponse(BaseModel):
    product_id: int
    type: str
    name: str
    description: str
    interest_rate: Decimal
    min_amount: int | None  # 예금 상품만 값이 있음(최소 가입 금액)

    model_config = ConfigDict(from_attributes=True)


class CardProductResponse(BaseModel):
    product_id: int
    type: str
    name: str
    description: str
    credit_limit: int | None  # 신용카드 상품만 값이 있음

    model_config = ConfigDict(from_attributes=True)


class FavoriteProductResponse(BaseModel):
    """찜한 상품 한 건: 상품 정보를 함께 준다 (홈 목록과 AI 비서가 같이 쓴다)."""

    product_type: str  # CHECKING / DEPOSIT / SAVINGS / CREDIT / DEBIT
    product_id: int
    name: str
    description: str
    interest_rate: Decimal | None  # 계좌 상품만 (연 %)
    min_amount: int | None  # 예금 상품만 (최소 가입 금액)
    credit_limit: int | None  # 신용카드 상품만
