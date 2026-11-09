"""예·적금 가입 화면을 미리 채운다 (C-103). 가입은 하지 않는다.

가입에는 약관 동의와 계좌 비밀번호가 필요하고, 둘 다 사용자가 가입 화면에서 직접 한다(대화로 받지 않는다).
그래서 이 도구는 상품·금액·만기일 같은 값을 검증해 카드로 돌려주고, 카드의 버튼이 값이 채워진 가입 화면을 연다.
"""

import calendar
from datetime import date
from typing import Literal

from pydantic import Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.exceptions import BadRequestException, NotFoundException
from avengers_bank.core.timezone import today_kst
from avengers_bank.domains.accounts.schemas import Amount
from avengers_bank.domains.agent.schemas import OpenAccountAction, SummaryRow
from avengers_bank.domains.agent.tools.common import ToolArgs
from avengers_bank.domains.agent.tools.transfers import find_own_checking, name_key
from avengers_bank.domains.products.models import AccountProduct
from avengers_bank.domains.products.service import product_service
from avengers_bank.domains.users.schemas import UserResponse

TYPES = {"deposit": "DEPOSIT", "savings": "SAVINGS"}
LABELS = {"deposit": "예금", "savings": "적금"}


class PrepareOpenAccountArgs(ToolArgs):
    kind: Literal["deposit", "savings"] = Field(description="예금은 deposit, 적금은 savings")
    product: str | None = Field(
        default=None, min_length=1, max_length=50,
        description="사용자가 말한 상품 이름. 말하지 않았으면 비워 둔다(서버가 상품 목록을 돌려준다)")
    amount: Amount | None = Field(default=None, description="예금은 가입 금액(원), 적금은 매월 납입액(원)")
    maturity_months: int | None = Field(
        default=None, ge=1, le=120,
        description="오늘부터 몇 개월 뒤가 만기인지 ('2년 뒤'는 24, '1년'은 12). 날짜는 서버가 계산한다")
    maturity_date: date | None = Field(
        default=None, description="사용자가 만기 날짜를 직접 말했을 때만 YYYY-MM-DD. maturity_months와 같이 쓰지 않는다")
    monthly_deposit_date: int | None = Field(default=None, ge=1, le=31, description="적금의 매월 납입일(1~31)")
    from_account: str | None = Field(
        default=None, min_length=1, max_length=50,
        description="예금 가입 금액을 낼 내 입출금 계좌 이름(별칭·상품명) 또는 번호 끝 4자리")
    nickname: str | None = Field(default=None, min_length=1, max_length=50, description="계좌 별명")

    @model_validator(mode="after")
    def _one_maturity(self):
        if self.maturity_months is not None and self.maturity_date is not None:
            raise ValueError("maturity_months와 maturity_date는 둘 중 하나만 넣어야 합니다.")
        return self


def add_months(day: date, months: int) -> date:
    """말일을 넘기면 그 달 말일로 (1월 31일 + 1개월 = 2월 28일)."""
    year, month = divmod(day.month - 1 + months, 12)
    year, month = day.year + year, month + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _describe(p: AccountProduct) -> str:
    extra = f", 최소 {p.min_amount:,}원" if p.min_amount else ""
    return f"{p.name}(연 {p.interest_rate.normalize():f}%{extra})"


def _pick_product(products: list[AccountProduct], ref: str | None, label: str) -> AccountProduct:
    """상품 이름으로 하나를 찾는다. 이름이 없고 상품이 하나뿐이면 그 상품. 없거나 여럿이면 후보를 오류로 돌려 되묻게 한다."""
    if ref is None and len(products) == 1:
        return products[0]
    key = name_key(ref or "")
    found: list[AccountProduct] = []
    if key:
        found = [p for p in products if name_key(p.name) == key] or [
            p for p in products if key in name_key(p.name) or name_key(p.name) in key
        ]
    if len(found) == 1:
        return found[0]
    shown = found or products
    message = f"{label} 상품: {', '.join(_describe(p) for p in shown)}. 사용자에게 어느 상품인지 물어보세요."
    if ref is None:
        raise BadRequestException(code="PRODUCT_NOT_SPECIFIED", message=f"어느 {label} 상품인지 정해야 합니다. {message}")
    if not found:
        raise NotFoundException(code="PRODUCT_NOT_FOUND", message=f"'{ref}'에 해당하는 {label} 상품이 없습니다. {message}")
    raise BadRequestException(code="PRODUCT_AMBIGUOUS", message=f"'{ref}'에 해당하는 상품이 여러 개입니다. {message}")


async def prepare_open_account(db: AsyncSession, user: UserResponse, args: PrepareOpenAccountArgs) -> OpenAccountAction:
    label = LABELS[args.kind]
    product = _pick_product(await product_service.get_account_products(db, TYPES[args.kind]), args.product, label)
    # find_own_checking이 트랜잭션을 닫으면 ORM 객체가 만료되므로, 쓸 값은 미리 꺼내 둔다
    product_id, name, rate, min_amount = product.product_id, product.name, product.interest_rate, product.min_amount

    maturity = args.maturity_date or (add_months(today_kst(), args.maturity_months) if args.maturity_months else None)
    if maturity is not None and maturity <= today_kst():
        raise BadRequestException(code="MATURITY_NOT_FUTURE", message="만기일은 내일 이후여야 합니다.")
    if args.kind == "deposit" and args.amount is not None and min_amount and args.amount < min_amount:
        raise BadRequestException(
            code="AMOUNT_BELOW_MINIMUM",
            message=f"{name}의 최소 가입 금액은 {min_amount:,}원입니다.",
        )

    fields: dict[str, str] = {}
    rows = [SummaryRow(label="상품", value=name)]
    if args.amount is not None:
        fields["initial_amount" if args.kind == "deposit" else "monthly_payment"] = str(args.amount)
        rows.append(SummaryRow(label="가입 금액" if args.kind == "deposit" else "매월 납입액", value=f"{args.amount:,}원"))
    if args.monthly_deposit_date is not None and args.kind == "savings":
        fields["monthly_deposit_date"] = str(args.monthly_deposit_date)
        rows.append(SummaryRow(label="매월 납입일", value=f"{args.monthly_deposit_date}일"))
    if maturity is not None:
        fields["maturity_date"] = maturity.isoformat()
        rows.append(SummaryRow(label="만기일", value=maturity.isoformat()))
    if args.from_account is not None and args.kind == "deposit":
        account_id, _, account = await find_own_checking(db, user, args.from_account, "FROM")
        fields["checking_account_id"] = str(account_id)
        rows.append(SummaryRow(label="출금 계좌", value=account))
    if args.nickname is not None:
        fields["nickname"] = args.nickname.strip()
        rows.append(SummaryRow(label="별명", value=args.nickname.strip()))

    return OpenAccountAction(
        kind=args.kind, product_id=product_id, product_name=name,
        interest_rate=f"{rate.normalize():f}", summary=rows, fields=fields,
    )
