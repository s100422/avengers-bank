from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class AccountProductResponse(BaseModel):
    product_id: int
    type: str
    name: str
    description: str
    interest_rate: Decimal

    model_config = ConfigDict(from_attributes=True)


class CardProductResponse(BaseModel):
    product_id: int
    type: str
    name: str
    description: str
    credit_limit: int | None  # 신용카드 상품만 값이 있음

    model_config = ConfigDict(from_attributes=True)
