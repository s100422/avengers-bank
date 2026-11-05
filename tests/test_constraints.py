from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.accounts.models import (
    CheckingAccount,
    CheckingAccountHistory,
    SavingsAccount,
)
from avengers_bank.domains.cards.models import CreditCard, CreditCardBill
from avengers_bank.domains.products.models import AccountProduct, CardProduct
from avengers_bank.domains.users.models import User

pytestmark = pytest.mark.anyio


async def _seed(db):
    user = User(login_id="ironman", hashed_password="x", name="토니", phone="010-0000-0000")
    product = AccountProduct(type="CHECKING", name="기본", description="", interest_rate=0)
    db.add_all([user, product])
    await db.flush()
    return user, product


@pytest.mark.parametrize(
    "make_row",
    [
        lambda u, p: AccountProduct(type="LOAN", name="x", description="", interest_rate=0),
        lambda u, p: CardProduct(type="PREPAID", name="x", description=""),
        lambda u, p: CheckingAccount(
            user_id=u.user_id, product_id=p.product_id, account_num="1", balance=-1,
            per_transfer_limit=1, daily_transfer_limit=1,
        ),
        lambda u, p: CheckingAccount(
            user_id=u.user_id, product_id=p.product_id, account_num="3", balance=0,
            per_transfer_limit=2, daily_transfer_limit=1,
        ),
        lambda u, p: SavingsAccount(
            user_id=u.user_id, product_id=p.product_id, account_num="2", balance=0,
            monthly_payment=1, monthly_deposit_date=32, maturity_date=date(2030, 1, 1),
        ),
    ],
    ids=["account_product_type", "card_product_type", "negative_balance", "per_over_daily", "deposit_date_32"],
)
async def test_check_constraints_reject_invalid_rows(client, make_row):
    async with SessionLocal() as db:
        user, product = await _seed(db)
        db.add(make_row(user, product))
        with pytest.raises(IntegrityError):
            await db.flush()


async def test_credit_card_payment_date_range(client):
    async with SessionLocal() as db:
        user, product = await _seed(db)
        account = CheckingAccount(
            user_id=user.user_id, product_id=product.product_id, account_num="1",
            per_transfer_limit=1, daily_transfer_limit=1,
        )
        card_product = CardProduct(type="CREDIT", name="x", description="", credit_limit=100_000)
        db.add_all([account, card_product])
        await db.flush()
        db.add(CreditCard(
            user_id=user.user_id, product_id=card_product.product_id,
            checking_account_id=account.checking_account_id, card_num="1", payment_date=0,
            credit_limit=1_000_000,
        ))
        with pytest.raises(IntegrityError):
            await db.flush()


@pytest.mark.parametrize(("amount", "balance_after"), [(0, 0), (-1000, 0), (1000, -1)])
async def test_account_history_amount_and_balance_after(client, amount, balance_after):
    async with SessionLocal() as db:
        user, product = await _seed(db)
        account = CheckingAccount(
            user_id=user.user_id, product_id=product.product_id, account_num="1",
            per_transfer_limit=1, daily_transfer_limit=1,
        )
        db.add(account)
        await db.flush()
        db.add(CheckingAccountHistory(
            checking_account_id=account.checking_account_id, amount=amount,
            balance_after=balance_after, type="WITHDRAW",
        ))
        with pytest.raises(IntegrityError):
            await db.flush()


async def _seed_credit_card(db):
    user, product = await _seed(db)
    account = CheckingAccount(
        user_id=user.user_id, product_id=product.product_id, account_num="1",
        per_transfer_limit=1, daily_transfer_limit=1,
    )
    card_product = CardProduct(type="CREDIT", name="x", description="", credit_limit=100_000)
    db.add_all([account, card_product])
    await db.flush()
    card = CreditCard(
        user_id=user.user_id, product_id=card_product.product_id,
        checking_account_id=account.checking_account_id, card_num="1", payment_date=14,
        credit_limit=100_000,
    )
    db.add(card)
    await db.flush()
    return card


@pytest.mark.parametrize("outstanding", [-1, 100_001])
async def test_credit_card_outstanding_within_limit(client, outstanding):
    async with SessionLocal() as db:
        card = await _seed_credit_card(db)
        card.outstanding_amount = outstanding
        with pytest.raises(IntegrityError):
            await db.flush()


def _bill(card_id, **overrides):
    values = dict(
        credit_card_id=card_id, period_start=date(2026, 10, 1), period_end=date(2026, 10, 31),
        total_amount=80_000, due_date=date(2026, 11, 14),
    )
    return CreditCardBill(**(values | overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"total_amount": 0},
        {"period_end": date(2026, 9, 30)},
        {"status": "OVERDUE"},
        {"status": "PAID"},  # paid_at 없이 PAID
    ],
    ids=["zero_total", "period_reversed", "unknown_status", "paid_without_paid_at"],
)
async def test_credit_card_bill_constraints(client, overrides):
    async with SessionLocal() as db:
        card = await _seed_credit_card(db)
        db.add(_bill(card.credit_card_id, **overrides))
        with pytest.raises(IntegrityError):
            await db.flush()


async def test_credit_card_bill_one_per_period(client):
    async with SessionLocal() as db:
        card = await _seed_credit_card(db)
        db.add(_bill(card.credit_card_id))
        await db.flush()
        db.add(_bill(card.credit_card_id, total_amount=1))
        with pytest.raises(IntegrityError):
            await db.flush()


@pytest.mark.parametrize(
    ("product_type", "credit_limit"),
    [("CREDIT", None), ("CREDIT", 0), ("DEBIT", 100_000)],
    ids=["credit_without_limit", "credit_zero_limit", "debit_with_limit"],
)
async def test_card_product_credit_limit_by_type(client, product_type, credit_limit):
    async with SessionLocal() as db:
        db.add(CardProduct(type=product_type, name="x", description="", credit_limit=credit_limit))
        with pytest.raises(IntegrityError):
            await db.flush()


async def test_card_product_valid_credit_limit(client):
    async with SessionLocal() as db:
        db.add_all([
            CardProduct(type="CREDIT", name="x", description="", credit_limit=3_000_000),
            CardProduct(type="DEBIT", name="y", description=""),
        ])
        await db.flush()
