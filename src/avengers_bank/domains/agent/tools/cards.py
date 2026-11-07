import calendar
from datetime import date
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.timezone import today_kst
from avengers_bank.domains.accounts.kinds import KINDS as ACCOUNT_KINDS
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.agent.tools.accounts import NoArgs
from avengers_bank.domains.agent.tools.common import account_name, mask_num
from avengers_bank.domains.cards.kinds import KINDS
from avengers_bank.domains.cards.repository import card_repository
from avengers_bank.domains.users.schemas import UserResponse


class CardItem(BaseModel):
    card_type: str  # credit / debit
    card_num_masked: str
    status: str
    outstanding_amount: int | None  # 신용카드 미결제액 (청구 전 + 미납 청구서)
    unpaid_bill_total: int  # 미납 청구서 합계
    next_payment_date: date | None
    # BILL: 미납 청구서의 납부 예정일, PAYMENT_DAY: 청구서는 없지만 미결제액이 있어 다음 결제일을 계산
    next_payment_basis: Literal["BILL", "PAYMENT_DAY"] | None
    payment_account_name: str
    payment_account_num_masked: str


class PaymentAccountItem(BaseModel):
    name: str
    account_num_masked: str
    balance: int
    unpaid_bill_total: int
    outstanding_total: int
    shortfall_for_unpaid_bills: int  # 미납 청구서를 모두 내기에 부족한 금액 (0이면 충분)
    shortfall_for_outstanding: int  # 미결제액 전부를 내기에 부족한 금액


class CardPaymentStatus(BaseModel):
    cards: list[CardItem]
    payment_accounts: list[PaymentAccountItem]
    credit_outstanding_total: int
    unpaid_bill_total: int
    next_payment_date: date | None
    total_shortfall_for_unpaid_bills: int


def _next_payment_day(payment_date: int, today: date) -> date:
    """오늘 이후(오늘 포함) 첫 결제일. 그 달에 없는 날이면 말일."""
    year, month = today.year, today.month
    for _ in range(2):
        day = date(year, month, min(payment_date, calendar.monthrange(year, month)[1]))
        if day >= today:
            return day
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return day


async def get_card_payment_status(db: AsyncSession, user: UserResponse, args: NoArgs) -> CardPaymentStatus:
    today = today_kst()
    cards, accounts, names = [], {}, {}
    for kind in KINDS.values():
        for card in await card_repository.find_by_user_id(db, kind, user.user_id):
            if card.status == "CLOSED":
                continue
            acc_id = card.checking_account_id
            if acc_id not in accounts:
                account = await account_repository.find_by_id(db, ACCOUNT_KINDS["checking"], acc_id)
                accounts[acc_id] = {"account": account, "name": await account_name(db, account, names),
                                    "unpaid": 0, "outstanding": 0}
            entry = accounts[acc_id]
            unpaid, outstanding, next_day, basis = 0, None, None, None
            if kind.name == "credit":
                outstanding = card.outstanding_amount
                due = [b for b in await card_repository.find_bills(db, getattr(card, kind.id_column)) if b.status == "UNPAID"]
                unpaid = sum(b.total_amount for b in due)
                if due:
                    next_day, basis = min(b.due_date for b in due), "BILL"
                elif outstanding > 0:
                    next_day, basis = _next_payment_day(card.payment_date, today), "PAYMENT_DAY"
                entry["unpaid"] += unpaid
                entry["outstanding"] += outstanding
            cards.append(CardItem(
                card_type=kind.name, card_num_masked=mask_num(card.card_num), status=card.status,
                outstanding_amount=outstanding, unpaid_bill_total=unpaid, next_payment_date=next_day,
                next_payment_basis=basis, payment_account_name=entry["name"],
                payment_account_num_masked=mask_num(entry["account"].account_num),
            ))

    payment_accounts = [
        PaymentAccountItem(
            name=e["name"], account_num_masked=mask_num(e["account"].account_num), balance=e["account"].balance,
            unpaid_bill_total=e["unpaid"], outstanding_total=e["outstanding"],
            shortfall_for_unpaid_bills=max(0, e["unpaid"] - e["account"].balance),
            shortfall_for_outstanding=max(0, e["outstanding"] - e["account"].balance),
        )
        for e in accounts.values()
    ]
    dates = [c.next_payment_date for c in cards if c.next_payment_date]
    return CardPaymentStatus(
        cards=cards, payment_accounts=payment_accounts,
        credit_outstanding_total=sum(c.outstanding_amount or 0 for c in cards),
        unpaid_bill_total=sum(c.unpaid_bill_total for c in cards),
        next_payment_date=min(dates) if dates else None,
        total_shortfall_for_unpaid_bills=sum(p.shortfall_for_unpaid_bills for p in payment_accounts),
    )
