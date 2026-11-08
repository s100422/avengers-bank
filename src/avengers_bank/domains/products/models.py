from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class AccountProduct(Base):
    __tablename__ = "account_products"
    __table_args__ = (
        CheckConstraint(
            "type IN ('CHECKING', 'DEPOSIT', 'SAVINGS')", name="ck_account_products_type"
        ),
        # NULL = 최소 금액 없음(1원 이상). 예금 상품만 값을 가진다.
        CheckConstraint(
            "min_amount IS NULL OR min_amount > 0", name="ck_account_products_min_amount_positive"
        ),
    )

    product_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # CHECKING / DEPOSIT / SAVINGS
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # 약관 연결용 안정적인 코드 (docs/terms/manifest.json의 product_code, C-075). 약관 발행 때 채운다
    product_code: Mapped[str | None] = mapped_column(String(50), unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    interest_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)  # 연 금리(%)
    min_amount: Mapped[int | None] = mapped_column(BigInteger)  # 예금 최소 가입 금액(원)


class CardProduct(Base):
    __tablename__ = "card_products"
    __table_args__ = (
        CheckConstraint("type IN ('CREDIT', 'DEBIT')", name="ck_card_products_type"),
        # 신용카드 상품은 한도 필수, 체크카드 상품은 한도 없음.
        # IS NOT NULL을 빼면 NULL > 0 이 UNKNOWN이 되어 CHECK를 통과해 버린다.
        CheckConstraint(
            "(type = 'CREDIT' AND credit_limit IS NOT NULL AND credit_limit > 0)"
            " OR (type = 'DEBIT' AND credit_limit IS NULL)",
            name="ck_card_products_credit_limit_by_type",
        ),
    )

    product_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # CREDIT / DEBIT
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # 약관 연결용 안정적인 코드 (docs/terms/manifest.json의 product_code, C-075). 약관 발행 때 채운다
    product_code: Mapped[str | None] = mapped_column(String(50), unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # 이 상품으로 발급하는 신용카드의 한도(원). 발급 때 credit_cards.credit_limit으로 복사한다.
    credit_limit: Mapped[int | None] = mapped_column(BigInteger)
