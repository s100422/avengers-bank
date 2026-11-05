from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class CreditCard(Base):
    """신용카드"""

    __tablename__ = "credit_cards"
    __table_args__ = (
        CheckConstraint(
            "payment_date BETWEEN 1 AND 31", name="ck_credit_cards_payment_date_range"
        ),
        CheckConstraint("credit_limit > 0", name="ck_credit_cards_credit_limit_positive"),
        CheckConstraint(
            "status IN ('ACTIVE', 'SUSPENDED', 'CLOSED')", name="ck_credit_cards_status"
        ),
        # 동시 결제로 서비스의 한도 검사가 뚫려도 한도 초과·음수 미결제액은 DB가 막는다.
        CheckConstraint(
            "outstanding_amount BETWEEN 0 AND credit_limit",
            name="ck_credit_cards_outstanding_amount_within_limit",
        ),
    )

    credit_card_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.user_id"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("card_products.product_id"), nullable=False
    )
    checking_account_id: Mapped[int] = mapped_column(  # 결제 계좌
        ForeignKey("checking_accounts.checking_account_id"), nullable=False, index=True
    )
    card_num: Mapped[str] = mapped_column(String(19), unique=True, nullable=False)
    credit_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 신용 한도 (발급 때 상품 한도 복사)
    # 아직 갚지 않은 금액: 사용하면 증가, 청구서 납부하면 청구 금액만큼 감소
    outstanding_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    payment_date: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 매월 결제일(1~31)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", nullable=False)  # ACTIVE / SUSPENDED / CLOSED


class DebitCard(Base):
    """체크카드"""

    __tablename__ = "debit_cards"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'SUSPENDED', 'CLOSED')", name="ck_debit_cards_status"
        ),
    )

    debit_card_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.user_id"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("card_products.product_id"), nullable=False
    )
    checking_account_id: Mapped[int] = mapped_column(  # 출금 계좌
        ForeignKey("checking_accounts.checking_account_id"), nullable=False, index=True
    )
    card_num: Mapped[str] = mapped_column(String(19), unique=True, nullable=False)
    accumulated_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", nullable=False)  # ACTIVE / SUSPENDED / CLOSED


class CreditCardHistory(Base):
    """신용카드 사용내역"""

    __tablename__ = "credit_card_histories"
    __table_args__ = (
        Index("ix_credit_card_histories_card_time", "credit_card_id", "time"),
    )

    credit_card_history_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    credit_card_id: Mapped[int] = mapped_column(
        ForeignKey("credit_cards.credit_card_id"), nullable=False
    )
    place_of_use: Mapped[str] = mapped_column(String(100), nullable=False)
    used_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 이 사용내역이 포함된 청구서. NULL이면 아직 청구 전
    bill_id: Mapped[int | None] = mapped_column(
        ForeignKey("credit_card_bills.bill_id"), index=True
    )


class CreditCardBill(Base):
    """신용카드 청구서: 이용 기간(전월 1일~말일, KST)의 미청구 사용내역 합계"""

    __tablename__ = "credit_card_bills"
    __table_args__ = (
        # 같은 카드, 같은 이용 기간의 청구서는 하나만 (중복 생성 → 409)
        UniqueConstraint(
            "credit_card_id", "period_start", name="uq_credit_card_bills_card_period"
        ),
        CheckConstraint("total_amount > 0", name="ck_credit_card_bills_total_amount_positive"),
        CheckConstraint(
            "period_end >= period_start", name="ck_credit_card_bills_period_order"
        ),
        CheckConstraint("status IN ('UNPAID', 'PAID')", name="ck_credit_card_bills_status"),
        CheckConstraint(
            "(status = 'PAID') = (paid_at IS NOT NULL)",
            name="ck_credit_card_bills_paid_at_matches_status",
        ),
    )

    bill_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    credit_card_id: Mapped[int] = mapped_column(
        ForeignKey("credit_cards.credit_card_id"), nullable=False
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    total_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)  # 납부 예정일
    status: Mapped[str] = mapped_column(String(10), default="UNPAID", nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DebitCardHistory(Base):
    """체크카드 사용내역"""

    __tablename__ = "debit_card_histories"
    __table_args__ = (
        Index("ix_debit_card_histories_card_time", "debit_card_id", "time"),
    )

    debit_card_history_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    debit_card_id: Mapped[int] = mapped_column(
        ForeignKey("debit_cards.debit_card_id"), nullable=False
    )
    place_of_use: Mapped[str] = mapped_column(String(100), nullable=False)
    used_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
