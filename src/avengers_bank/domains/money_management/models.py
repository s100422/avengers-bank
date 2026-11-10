"""돈 관리 분석 정보. 원본 거래(계좌·카드 내역)는 바꾸지 않고 연결된 분석 값만 저장한다."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base
from avengers_bank.domains.money_management.domain import Category

_CATEGORY_IN = "IN (" + ", ".join(f"'{c.value}'" for c in Category) + ")"


class MerchantCategory(Base):
    """가맹점 이름 → 카테고리 캐시 (LLM 결과). 이름만 보고 정하므로 사용자와 무관하게 공유한다."""

    __tablename__ = "merchant_categories"
    __table_args__ = (CheckConstraint(f"category {_CATEGORY_IN}", name="ck_merchant_categories_category"),)

    merchant_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CategoryRule(Base):
    """사용자 규칙: '이 결제처에 앞으로 적용'."""

    __tablename__ = "money_category_rules"
    __table_args__ = (
        UniqueConstraint("user_id", "merchant_key", name="uq_money_category_rules_user_merchant"),
        CheckConstraint(f"category {_CATEGORY_IN}", name="ck_money_category_rules_category"),
    )

    rule_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False, index=True)
    merchant_key: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TransactionOverride(Base):
    """거래 한 건의 사용자 수정: '이번 거래만 변경'한 분류와 일회성 지출 표시.

    원본 거래가 세 테이블에 나뉘어 있어 FK 없이 (source, source_id)로 가리킨다.
    """

    __tablename__ = "money_transaction_overrides"
    __table_args__ = (
        UniqueConstraint("user_id", "source", "source_id", name="uq_money_overrides_user_source"),
        CheckConstraint("source IN ('credit', 'debit', 'checking')", name="ck_money_overrides_source"),
        CheckConstraint(f"category IS NULL OR category {_CATEGORY_IN}", name="ck_money_overrides_category"),
    )

    override_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    source_id: Mapped[int] = mapped_column(nullable=False)
    category: Mapped[str | None] = mapped_column(String(20))
    is_one_off: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RecurringItem(Base):
    """정기 거래. ACTIVE=예상에 포함, EXCLUDED=앞으로 예상에서 제외, DISMISSED='반복 거래 아님'(후보로 다시 띄우지 않음).

    예상에서 빼도 실제 구독·자동이체가 해지되는 것은 아니다.
    """

    __tablename__ = "money_recurring_items"
    __table_args__ = (
        CheckConstraint("direction IN ('IN', 'OUT')", name="ck_money_recurring_direction"),
        CheckConstraint("status IN ('ACTIVE', 'EXCLUDED', 'DISMISSED')", name="ck_money_recurring_status"),
        CheckConstraint("day_of_month BETWEEN 1 AND 31", name="ck_money_recurring_day"),
        CheckConstraint("amount >= 0", name="ck_money_recurring_amount"),
        CheckConstraint(f"category IS NULL OR category {_CATEGORY_IN}", name="ck_money_recurring_category"),
    )

    recurring_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    merchant_key: Mapped[str | None] = mapped_column(String(100))  # 자동 탐지 후보에서 온 경우 연결용
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    category: Mapped[str | None] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    day_of_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", nullable=False)
    skip_month: Mapped[str | None] = mapped_column(String(7))  # "YYYY-MM"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
