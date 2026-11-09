from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import update

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.timezone import today_kst
from avengers_bank.domains.accounts.interest import calc_interest, scheduled_payment_days
from avengers_bank.domains.accounts.kinds import KINDS
from tests.helpers import open_deposit

pytestmark = pytest.mark.anyio

FUTURE = (today_kst() + timedelta(days=365)).isoformat()
RATE = 1  # tests/conftest.py의 account_products 상품 금리는 모두 연 1%


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


# ── 이자 계산 (순수 함수) ─────────────────────────────────────────────


def test_interest_full_rate_after_maturity_counts_days_only_until_maturity():
    maturity = date(2027, 1, 1)
    # 365일 맡김, 연 3% → 30,000. 만기 뒤 100일 지나 해지해도 만기일까지만 센다
    assert calc_interest([(date(2026, 1, 1), 1_000_000)], Decimal("3.00"), maturity + timedelta(days=100), maturity) == 30_000


def test_interest_early_close_uses_half_rate():
    assert calc_interest([(date(2026, 1, 1), 1_000_000)], Decimal("3.00"), date(2027, 1, 1), date(2028, 1, 1)) == 15_000


def test_interest_sums_each_payment_by_its_own_days_and_floors():
    deposits = [(date(2026, 1, 1), 100_000), (date(2026, 7, 1), 100_000)]
    # 100,000 × 3.65% × 181/365 + 100,000 × 3.65% × 0 → 일수가 다른 두 건. 원 미만 버림
    assert calc_interest(deposits, Decimal("3.65"), date(2026, 7, 1), date(2026, 7, 1)) == 1_810
    assert calc_interest([(date(2026, 1, 1), 1_000)], Decimal("3.00"), date(2026, 1, 2), date(2026, 1, 2)) == 0  # 0.08원


def test_interest_zero_when_deposited_today_or_no_deposits():
    today = date(2026, 5, 1)
    assert calc_interest([(today, 1_000_000)], Decimal("3.00"), today, date(2027, 5, 1)) == 0
    assert calc_interest([], Decimal("3.00"), today, date(2027, 5, 1)) == 0


# ── 해지 API ─────────────────────────────────────────────────────────


@pytest.fixture
async def world(client, make_user, account_products):
    """토니: 입출금 1번(잔액 100만 원), 예금 1번(30만 원 입금), 적금 1번(20만 원 입금). 브루스: 입출금 2번."""
    tony, bruce = await make_user("ironman"), await make_user("hulk")
    await client.post("/accounts/checking", json={"product_id": 1}, headers=tony)
    await client.post("/accounts/checking", json={"product_id": 1}, headers=bruce)
    await client.post("/dev/accounts/checking/1/charge", json={"amount": 1_000_000}, headers=tony)
    await open_deposit(client, tony, 300_000, from_id=1)
    savings = {"product_id": 3, "monthly_payment": 100_000, "monthly_deposit_date": 25, "maturity_date": FUTURE}
    await client.post("/accounts/savings", json=savings, headers=tony)
    await client.post("/transfers/savings", json={"from_checking_account_id": 1, "savings_account_id": 1, "amount": 200_000}, headers=tony)
    return {"tony": tony, "bruce": bruce}  # 입출금 잔액 500,000


async def close(client, headers, kind, account_id=1, to=1):
    return await client.post(f"/accounts/{kind}/{account_id}/close", json={"to_checking_account_id": to}, headers=headers)


async def get(client, headers, kind, account_id=1):
    return (await client.get(f"/accounts/{kind}/{account_id}", headers=headers)).json()["data"]


async def backdate(kind, history_days_ago=None, maturity=None):
    """입금 내역의 날짜를 과거로, 만기일을 원하는 날로 바꿔서 이자가 생기게 한다."""
    k = KINDS[kind]
    async with SessionLocal() as db, db.begin():
        if history_days_ago is not None:
            await db.execute(update(k.history_model).values(date=today_kst_utc_minus(history_days_ago)))
        if maturity is not None:
            await db.execute(update(k.model).values(maturity_date=maturity))


def today_kst_utc_minus(days):
    from datetime import datetime, timezone

    return datetime.now(timezone.utc) - timedelta(days=days)


@pytest.mark.parametrize("kind, principal", [("deposit", 300_000), ("savings", 200_000)])
async def test_close_early_same_day_returns_principal_without_interest(client, world, kind, principal):
    tony = world["tony"]
    response = await close(client, tony, kind)
    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["principal"], data["interest"], data["total_amount"], data["early_close"]) == (principal, 0, principal, True)
    assert data["to_balance_after"] == 500_000 + principal

    account = await get(client, tony, kind)
    assert (account["status"], account["balance"]) == ("CLOSED", 0) and account["closed_at"] is not None
    assert (await get(client, tony, "checking"))["balance"] == 500_000 + principal


async def test_close_deposit_after_maturity_pays_full_rate_and_records_histories(client, world):
    tony = world["tony"]
    await backdate("deposit", history_days_ago=365, maturity=today_kst())  # 만기일 당일, 365일 전 입금
    data = (await close(client, tony, "deposit")).json()["data"]
    assert (data["principal"], data["interest"], data["early_close"]) == (300_000, 3_000, False)  # 30만 × 1% × 365/365
    assert data["total_amount"] == 303_000 and data["to_balance_after"] == 803_000

    rows = (await client.get("/accounts/deposit/1/histories", headers=tony)).json()["data"]
    assert [(r["type"], r["amount"], r["balance_after"]) for r in rows] == [
        ("CLOSE_OUT", 303_000, 0), ("INTEREST", 3_000, 303_000), ("TRANSFER_IN", 300_000, 300_000),
    ]
    checking = (await client.get("/accounts/checking/1/histories", headers=tony)).json()["data"][0]
    assert (checking["type"], checking["amount"], checking["balance_after"]) == ("CLOSE_IN", 303_000, 803_000)
    assert checking["counterpart_account"] == (await get(client, tony, "deposit"))["account_num"]


async def test_close_early_pays_half_rate(client, world):
    tony = world["tony"]
    await backdate("savings", history_days_ago=365)  # 만기는 1년 뒤라 중도 해지
    data = (await close(client, tony, "savings")).json()["data"]
    assert (data["interest"], data["early_close"]) == (1_000, True)  # 20만 × 1% × 0.5


async def test_closed_account_rejects_second_close(client, world):
    tony = world["tony"]
    await close(client, tony, "deposit")
    assert error_of(await close(client, tony, "deposit")) == (400, "ACCOUNT_CLOSED")
    # 거절된 요청은 돈을 움직이지 않는다
    assert (await get(client, tony, "checking"))["balance"] == 800_000


async def test_closed_savings_rejects_payment(client, world):
    tony = world["tony"]
    await close(client, tony, "savings")
    pay = {"from_checking_account_id": 1, "savings_account_id": 1, "amount": 1000}
    assert error_of(await client.post("/transfers/savings", json=pay, headers=tony)) == (400, "ACCOUNT_CLOSED")
    assert (await get(client, tony, "checking"))["balance"] == 700_000


async def test_close_errors_change_nothing(client, world):
    tony, bruce = world["tony"], world["bruce"]
    assert error_of(await close(client, tony, "checking")) == (400, "CLOSE_NOT_SUPPORTED")
    assert error_of(await close(client, bruce, "deposit")) == (404, "ACCOUNT_NOT_FOUND")  # 남의 예금
    assert error_of(await close(client, tony, "deposit", to=2)) == (404, "ACCOUNT_NOT_FOUND")  # 남의 입출금으로는 못 받음
    assert error_of(await close(client, tony, "deposit", account_id=99)) == (404, "ACCOUNT_NOT_FOUND")
    assert (await get(client, tony, "deposit"))["status"] == "ACTIVE"
    assert (await get(client, tony, "checking"))["balance"] == 500_000


async def test_close_empty_account_records_no_history(client, make_user, account_products):
    # 예금은 가입 금액이 있어야 열리므로 빈 계좌는 적금으로 확인한다
    tony = await make_user("ironman")
    await client.post("/accounts/checking", json={"product_id": 1}, headers=tony)
    savings = {"product_id": 3, "monthly_payment": 100_000, "monthly_deposit_date": 25, "maturity_date": FUTURE}
    await client.post("/accounts/savings", json=savings, headers=tony)
    data = (await close(client, tony, "savings")).json()["data"]
    assert (data["principal"], data["interest"], data["total_amount"]) == (0, 0, 0)
    assert (await client.get("/accounts/savings/1/histories", headers=tony)).json()["data"] == []
    assert (await get(client, tony, "savings"))["status"] == "CLOSED"


async def test_summary_list_shows_status(client, world):
    tony = world["tony"]
    await close(client, tony, "savings")
    rows = {r["account_type"]: r["status"] for r in (await client.get("/accounts", headers=tony)).json()["data"]}
    assert rows == {"checking": None, "deposit": "ACTIVE", "savings": "CLOSED"}


# ── 이자 미리 보기 (C-104) ───────────────────────────────────────────


def test_scheduled_payment_days_clamps_to_month_end_and_excludes_today():
    assert scheduled_payment_days(date(2026, 11, 9), date(2027, 2, 9), 31) == [date(2026, 11, 30), date(2026, 12, 31), date(2027, 1, 31)]
    assert scheduled_payment_days(date(2026, 11, 9), date(2026, 12, 9), 9) == [date(2026, 12, 9)]  # 오늘(11/9)은 빼고, 만기일 당일은 넣는다
    assert scheduled_payment_days(date(2026, 11, 9), date(2026, 11, 9), 9) == []


async def preview(client, headers, kind, account_id=1):
    return await client.get(f"/accounts/{kind}/{account_id}/interest-preview", headers=headers)


async def test_interest_preview_deposit_and_it_matches_the_real_close(client, world):
    tony = world["tony"]
    await backdate("deposit", history_days_ago=200)  # 만기는 365일 뒤
    data = (await preview(client, tony, "deposit")).json()["data"]
    # 오늘 해지: 30만 × 1% × 0.5 × 200/365 = 821.9 → 821. 만기: 30만 × 1% × 565/365 = 4,643.8 → 4,643
    assert (data["close_today_interest"], data["close_today_early"], data["close_today_rate"], data["interest_rate"]) == (821, True, "0.5", "1")
    assert (data["maturity_principal"], data["maturity_interest"], data["maturity_total"]) == (300_000, 4_643, 304_643)
    assert (data["assumed_payments"], data["monthly_payment"]) == (0, None)
    assert data["maturity_date"] == FUTURE
    real = (await close(client, tony, "deposit")).json()["data"]  # 미리 본 값이 실제 해지 결과와 같다
    assert (real["interest"], real["total_amount"]) == (data["close_today_interest"], data["close_today_total"])


async def test_interest_preview_savings_assumes_monthly_payments_continue(client, world):
    tony = world["tony"]
    await backdate("savings", history_days_ago=100)
    data = (await preview(client, tony, "savings")).json()["data"]
    today, maturity = today_kst(), today_kst() + timedelta(days=365)
    days = scheduled_payment_days(today, maturity, 25)
    projected = [(today - timedelta(days=100), 200_000)] + [(d, 100_000) for d in days]
    assert data["assumed_payments"] == len(days) and data["monthly_payment"] == 100_000
    assert data["maturity_principal"] == 200_000 + 100_000 * len(days)
    assert data["maturity_interest"] == calc_interest(projected, Decimal(RATE), maturity, maturity)
    assert data["close_today_principal"] == 200_000  # 오늘 해지는 지금까지 넣은 돈만
    real = (await close(client, tony, "savings")).json()["data"]
    assert (real["interest"], real["total_amount"]) == (data["close_today_interest"], data["close_today_total"])


async def test_interest_preview_after_maturity_uses_full_rate(client, world):
    tony = world["tony"]
    await backdate("deposit", history_days_ago=365, maturity=today_kst())
    data = (await preview(client, tony, "deposit")).json()["data"]
    assert (data["close_today_interest"], data["close_today_early"], data["close_today_rate"]) == (3_000, False, "1")
    assert (data["maturity_interest"], data["maturity_total"]) == (3_000, 303_000)  # 만기 뒤에는 이자가 늘지 않는다


async def test_interest_preview_rejects_checking_closed_and_other_users(client, world):
    tony, bruce = world["tony"], world["bruce"]
    assert error_of(await preview(client, tony, "checking")) == (400, "INTEREST_NOT_SUPPORTED")
    assert error_of(await preview(client, bruce, "deposit")) == (404, "ACCOUNT_NOT_FOUND")  # 남의 계좌
    await close(client, tony, "deposit")
    assert error_of(await preview(client, tony, "deposit")) == (400, "ACCOUNT_CLOSED")
