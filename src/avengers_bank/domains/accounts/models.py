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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class CheckingAccount(Base):
    """입출금 계좌"""

    __tablename__ = "checking_accounts"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_checking_accounts_balance_non_negative"),
        CheckConstraint(
            "per_transfer_limit <= daily_transfer_limit", name="ck_checking_accounts_limit_order"
        ),
    )

    checking_account_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.user_id"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("account_products.product_id"), nullable=False
    )
    account_num: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    per_transfer_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)
    daily_transfer_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DepositAccount(Base):
    """예금 계좌"""

    __tablename__ = "deposit_accounts"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_deposit_accounts_balance_non_negative"),
        CheckConstraint("status IN ('ACTIVE', 'CLOSED')", name="ck_deposit_accounts_status"),
        CheckConstraint(
            "(status = 'CLOSED') = (closed_at IS NOT NULL)", name="ck_deposit_accounts_closed_at_matches_status"
        ),
    )

    deposit_account_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.user_id"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("account_products.product_id"), nullable=False
    )
    account_num: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    maturity_date: Mapped[date] = mapped_column(Date, nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", nullable=False)  # ACTIVE / CLOSED
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SavingsAccount(Base):
    """적금 계좌"""

    __tablename__ = "savings_accounts"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_savings_accounts_balance_non_negative"),
        CheckConstraint("status IN ('ACTIVE', 'CLOSED')", name="ck_savings_accounts_status"),
        CheckConstraint(
            "(status = 'CLOSED') = (closed_at IS NOT NULL)", name="ck_savings_accounts_closed_at_matches_status"
        ),
        CheckConstraint(
            "monthly_deposit_date BETWEEN 1 AND 31",
            name="ck_savings_accounts_monthly_deposit_date_range",
        ),
    )

    savings_account_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.user_id"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("account_products.product_id"), nullable=False
    )
    account_num: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    monthly_payment: Mapped[int] = mapped_column(BigInteger, nullable=False)
    monthly_deposit_date: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 매월 납입일(1~31)
    maturity_date: Mapped[date] = mapped_column(Date, nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", nullable=False)  # ACTIVE / CLOSED
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CheckingAccountHistory(Base):
    """입출금 계좌 거래내역 (ERD: Chenking_Account_History)"""

    __tablename__ = "checking_account_histories"
    # 거래내역 조회(계좌별, 날짜순)와 1일 이체 한도 합계(계좌 + 오늘 날짜 범위)용
    __table_args__ = (
        Index("ix_checking_account_histories_account_date", "checking_account_id", "date"),
        CheckConstraint("amount > 0", name="ck_checking_account_histories_amount_positive"),
        CheckConstraint(
            "balance_after >= 0", name="ck_checking_account_histories_balance_after_non_negative"
        ),
        CheckConstraint("type IN ('TRANSFER_OUT', 'TRANSFER_IN', 'TO_SAVINGS', 'TO_DEPOSIT', 'CARD_PAYMENT', 'CARD_BILL_PAYMENT', 'DEV_CHARGE', 'CLOSE_IN')", name="ck_checking_account_histories_type"),
    )

    checking_account_history_id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True
    )
    checking_account_id: Mapped[int] = mapped_column(
        ForeignKey("checking_accounts.checking_account_id"), nullable=False
    )
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 금액은 항상 양수, 입금/출금 방향은 type으로 구분한다.
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 거래 후 잔액
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # 입금/출금/이체/카드결제 등
    # 상대 계좌번호: 입금이면 보낸 계좌, 출금이면 받는 계좌
    counterpart_account: Mapped[str | None] = mapped_column(String(20))
    # 상대 이름: 체크카드 결제의 가맹점명 (C-035)
    counterpart_name: Mapped[str | None] = mapped_column(String(100))


class DepositAccountHistory(Base):
    """예금 계좌 거래내역"""

    __tablename__ = "deposit_account_histories"
    __table_args__ = (
        Index("ix_deposit_account_histories_account_date", "deposit_account_id", "date"),
        CheckConstraint("amount > 0", name="ck_deposit_account_histories_amount_positive"),
        CheckConstraint(
            "balance_after >= 0", name="ck_deposit_account_histories_balance_after_non_negative"
        ),
        CheckConstraint(
            "type IN ('TRANSFER_IN', 'INTEREST', 'CLOSE_OUT')", name="ck_deposit_account_histories_type"
        ),
    )

    deposit_account_history_id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True
    )
    deposit_account_id: Mapped[int] = mapped_column(
        ForeignKey("deposit_accounts.deposit_account_id"), nullable=False
    )
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 금액은 항상 양수, 입금/출금 방향은 type으로 구분한다.
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 거래 후 잔액
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    # 상대 계좌번호: 입금이면 보낸 계좌, 출금이면 받는 계좌
    counterpart_account: Mapped[str | None] = mapped_column(String(20))


class SavingsAccountHistory(Base):
    """적금 계좌 거래내역"""

    __tablename__ = "savings_account_histories"
    __table_args__ = (
        Index("ix_savings_account_histories_account_date", "savings_account_id", "date"),
        CheckConstraint("amount > 0", name="ck_savings_account_histories_amount_positive"),
        CheckConstraint(
            "balance_after >= 0", name="ck_savings_account_histories_balance_after_non_negative"
        ),
        CheckConstraint(
            "type IN ('TRANSFER_IN', 'INTEREST', 'CLOSE_OUT')", name="ck_savings_account_histories_type"
        ),
    )

    savings_account_history_id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True
    )
    savings_account_id: Mapped[int] = mapped_column(
        ForeignKey("savings_accounts.savings_account_id"), nullable=False
    )
    date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 금액은 항상 양수, 입금/출금 방향은 type으로 구분한다.
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 거래 후 잔액
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    # 상대 계좌번호: 입금이면 보낸 계좌, 출금이면 받는 계좌
    counterpart_account: Mapped[str | None] = mapped_column(String(20))
