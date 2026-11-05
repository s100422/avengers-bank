"""신용카드·체크카드의 차이를 한 곳에 모아 둔다 (accounts/kinds.py와 같은 방식)."""

from dataclasses import dataclass
from typing import Literal

from avengers_bank.domains.cards.models import (
    CreditCard,
    CreditCardHistory,
    DebitCard,
    DebitCardHistory,
)

CardType = Literal["credit", "debit"]

# 입출금 거래내역 type 값 (최종 목록은 팀 결정 대기, docs/ERD.md)
CARD_PAYMENT = "CARD_PAYMENT"  # 체크카드 결제로 나간 돈
CARD_BILL_PAYMENT = "CARD_BILL_PAYMENT"  # 신용카드 청구서 납부로 나간 돈


@dataclass(frozen=True)
class CardKind:
    name: CardType
    model: type
    id_column: str  # 모델의 PK 컬럼 이름 (사용내역 테이블의 FK 컬럼 이름과 같다)
    history_model: type
    history_id_column: str
    product_type: str  # card_products.type 값
    prefix: str  # 카드번호 앞자리 (종류가 달라서 신용·체크 사이에 번호가 겹치지 않는다)


KINDS: dict[str, CardKind] = {
    "credit": CardKind(
        "credit", CreditCard, "credit_card_id",
        CreditCardHistory, "credit_card_history_id", "CREDIT", "4000",
    ),
    "debit": CardKind(
        "debit", DebitCard, "debit_card_id",
        DebitCardHistory, "debit_card_history_id", "DEBIT", "5000",
    ),
}
