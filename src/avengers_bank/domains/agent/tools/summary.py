from datetime import date

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.timezone import today_kst
from avengers_bank.domains.agent.tools.accounts import NoArgs, list_active_accounts
from avengers_bank.domains.agent.tools.cards import get_card_payment_status
from avengers_bank.domains.users.schemas import UserResponse


class MaturityItem(BaseModel):
    account_type: str
    name: str
    account_num_masked: str
    balance: int
    maturity_date: date
    days_left: int  # 오늘(KST)부터 만기일까지, 지났으면 0 이하


class FinancialSummary(BaseModel):
    active_account_count: int
    total_balance: int
    checking_balance: int
    deposit_balance: int
    savings_balance: int
    credit_outstanding_total: int
    unpaid_bill_total: int
    next_card_payment_date: date | None
    maturities: list[MaturityItem]  # 만기일이 가까운 순


async def get_financial_summary(db: AsyncSession, user: UserResponse, args: NoArgs) -> FinancialSummary:
    accounts = await list_active_accounts(db, user)
    cards = await get_card_payment_status(db, user, args)
    today = today_kst()

    def total(t: str) -> int:
        return sum(a.balance for a in accounts if a.account_type == t)

    maturities = sorted(
        (
            MaturityItem(
                account_type=a.account_type, name=a.name, account_num_masked=a.account_num_masked,
                balance=a.balance, maturity_date=a.maturity_date, days_left=(a.maturity_date - today).days,
            )
            for a in accounts if a.maturity_date
        ),
        key=lambda m: m.maturity_date,
    )
    return FinancialSummary(
        active_account_count=len(accounts), total_balance=sum(a.balance for a in accounts),
        checking_balance=total("checking"), deposit_balance=total("deposit"), savings_balance=total("savings"),
        credit_outstanding_total=cards.credit_outstanding_total, unpaid_bill_total=cards.unpaid_bill_total,
        next_card_payment_date=cards.next_payment_date, maturities=maturities,
    )
