"""돈 관리 도메인의 공통 계약. 분류(classification)·집계(analytics)·반복 탐지(recurring)가 함께 쓴다.

이 파일의 타입은 DB를 모른다. service.py가 원본 거래를 Txn으로 바꿔 넘기고, 각 모듈은 순수 함수로 계산한다.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Literal


class Category(StrEnum):
    DINING = "DINING"
    CAFE = "CAFE"
    MART = "MART"
    BEAUTY = "BEAUTY"
    ONLINE = "ONLINE"
    SUBSCRIPTION = "SUBSCRIPTION"
    TRANSPORT = "TRANSPORT"
    HOUSING = "HOUSING"
    MEDICAL = "MEDICAL"
    LEISURE = "LEISURE"
    TRANSFER = "TRANSFER"
    ETC = "ETC"  # 사용자가 확인했지만 맞는 항목이 없음
    UNCLASSIFIED = "UNCLASSIFIED"  # 근거가 부족해 확인이 필요함


LABELS: dict[Category, str] = {
    Category.DINING: "외식",
    Category.CAFE: "카페",
    Category.MART: "마트·편의점",
    Category.BEAUTY: "뷰티·생활",
    Category.ONLINE: "온라인쇼핑",
    Category.SUBSCRIPTION: "구독·디지털",
    Category.TRANSPORT: "교통",
    Category.HOUSING: "주거·통신",
    Category.MEDICAL: "의료",
    Category.LEISURE: "여가·문화",
    Category.TRANSFER: "이체",
    Category.ETC: "기타",
    Category.UNCLASSIFIED: "미분류",
}

# LLM이 고를 수 있는 값. 이체는 거래 type으로 정하므로 LLM 선택지에서 뺀다
LLM_CATEGORIES = [c for c in Category if c is not Category.TRANSFER]

# 입출금 계좌 내역 중 소비로 세는 type (본인 계좌 이동은 service가 빼서 is_self_transfer로 표시한다).
# CARD_PAYMENT는 체크카드 사용내역과 같은 거래, CARD_BILL_PAYMENT는 이미 센 신용카드 구매의 대금이라 소비가 아니다.
SPENDING_CHECKING_TYPES = {"TRANSFER_OUT", "INTERBANK_OUT"}
INCOME_CHECKING_TYPES = {"TRANSFER_IN", "INTERBANK_IN"}

Source = Literal["credit", "debit", "checking"]
Direction = Literal["IN", "OUT"]
# OVERRIDE=거래 한 건 수정, RULE=사용자 규칙, LLM=가맹점 분류(저장된 LLM 결과 포함), TYPE=거래 type(이체), NONE=분류 없음
CategorySource = Literal["OVERRIDE", "RULE", "LLM", "TYPE", "NONE"]


@dataclass
class Txn:
    """분석에 쓰는 거래 한 건. 카드 사용내역과 입출금 계좌 내역을 같은 모양으로 맞춘 것."""

    source: Source
    source_id: int
    occurred_at: datetime  # KST
    amount: int  # 항상 양수
    direction: Direction
    merchant: str | None  # 카드 가맹점명 또는 계좌 상대방 이름
    merchant_key: str | None  # classification.merchant_key(merchant)
    checking_type: str | None  # source == "checking"일 때 원본 type
    payment_label: str  # 화면 표시용 결제 수단 (예: "신용카드 ****1234")
    category: Category | None = None  # 소비가 아니면 None
    category_source: CategorySource = "NONE"
    is_one_off: bool = False  # 일회성 지출: 이번 달 합계에는 포함, 평소 추정에서 제외
    is_self_transfer: bool = False

    @property
    def is_spending(self) -> bool:
        """소비 분석에 들어가는 거래. 카드 구매 + (본인 이동이 아닌) 이체 출금. 사용자가 분류를 지정하면 포함."""
        if self.source in ("credit", "debit"):
            return True
        if self.category_source == "OVERRIDE":
            return self.direction == "OUT"
        return self.checking_type in SPENDING_CHECKING_TYPES and not self.is_self_transfer

    @property
    def is_income(self) -> bool:
        return self.source == "checking" and self.checking_type in INCOME_CHECKING_TYPES and not self.is_self_transfer


@dataclass
class RecurringRule:
    """사용자가 등록한 정기 거래 (models.RecurringItem과 같은 내용)."""

    recurring_id: int
    name: str
    merchant_key: str | None
    direction: Direction
    category: Category | None
    amount: int
    day_of_month: int  # 1~31, 짧은 달은 말일로 본다
    status: Literal["ACTIVE", "EXCLUDED", "DISMISSED"]
    skip_month: str | None  # "YYYY-MM": 이번 달만 건너뛰기


@dataclass
class Bill:
    """미납 신용카드 청구서 (확정 카드대금)."""

    bill_id: int
    due_date: date
    total_amount: int
    card_label: str
    credit_card_id: int | None = None  # 화면의 '청구 내역 보기' 링크용
