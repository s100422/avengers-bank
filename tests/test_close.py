from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import update

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.timezone import today_kst
from avengers_bank.domains.accounts.interest import calc_interest
from avengers_bank.domains.accounts.kinds import KINDS

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
    await client.post("/accounts/deposit", json={"product_id": 2, "maturity_date": FUTURE}, headers=tony)
    savings = {"product_id": 3, "monthly_payment": 100_000, "monthly_deposit_date": 25, "maturity_date": FUTURE}
    await client.post("/accounts/savings", json=savings, headers=tony)
    await client.post("/dev/accounts/checking/1/charge", json={"amount": 1_000_000}, headers=tony)
    await client.post("/transfers/deposit", json={"from_checking_account_id": 1, "deposit_account_id": 1, "amount": 300_000}, headers=tony)
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


async def test_closed_account_rejects_deposit_and_second_close(client, world):
    tony = world["tony"]
    await close(client, tony, "deposit")
    pay = {"from_checking_account_id": 1, "deposit_account_id": 1, "amount": 1000}
    assert error_of(await client.post("/transfers/deposit", json=pay, headers=tony)) == (400, "ACCOUNT_CLOSED")
    assert error_of(await close(client, tony, "deposit")) == (400, "ACCOUNT_CLOSED")
    # 거절된 요청은 돈을 움직이지 않는다
    assert (await get(client, tony, "checking"))["balance"] == 800_000


async def test_close_errors_change_nothing(client, world):
    tony, bruce = world["tony"], world["bruce"]
    assert error_of(await close(client, tony, "checking")) == (400, "CLOSE_NOT_SUPPORTED")
    assert error_of(await close(client, bruce, "deposit")) == (404, "ACCOUNT_NOT_FOUND")  # 남의 예금
    assert error_of(await close(client, tony, "deposit", to=2)) == (404, "ACCOUNT_NOT_FOUND")  # 남의 입출금으로는 못 받음
    assert error_of(await close(client, tony, "deposit", account_id=99)) == (404, "ACCOUNT_NOT_FOUND")
    assert (await get(client, tony, "deposit"))["status"] == "ACTIVE"
    assert (await get(client, tony, "checking"))["balance"] == 500_000


async def test_close_empty_account_records_no_history(client, make_user, account_products):
    tony = await make_user("ironman")
    await client.post("/accounts/checking", json={"product_id": 1}, headers=tony)
    await client.post("/accounts/deposit", json={"product_id": 2, "maturity_date": FUTURE}, headers=tony)
    data = (await close(client, tony, "deposit")).json()["data"]
    assert (data["principal"], data["interest"], data["total_amount"]) == (0, 0, 0)
    assert (await client.get("/accounts/deposit/1/histories", headers=tony)).json()["data"] == []
    assert (await get(client, tony, "deposit"))["status"] == "CLOSED"


async def test_summary_list_shows_status(client, world):
    tony = world["tony"]
    await close(client, tony, "savings")
    rows = {r["account_type"]: r["status"] for r in (await client.get("/accounts", headers=tony)).json()["data"]}
    assert rows == {"checking": None, "deposit": "ACTIVE", "savings": "CLOSED"}
