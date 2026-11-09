"""예금 상품별 최소 가입 금액."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.timezone import today_kst
from avengers_bank.domains.accounts.models import DepositAccount
from avengers_bank.domains.products.models import AccountProduct
from avengers_bank.domains.terms.models import TermsConsent

pytestmark = pytest.mark.anyio

FUTURE = (today_kst() + timedelta(days=365)).isoformat()


@pytest.fixture
async def world(client, make_user):
    """입출금 1번(잔액 200만 원). 상품: 1 입출금, 2 예금(최소 10만 원), 3 예금(최소 없음)."""
    async with SessionLocal() as db, db.begin():
        db.add_all([
            AccountProduct(type="CHECKING", name="입출금", description="d", interest_rate=1),
            AccountProduct(type="DEPOSIT", name="최소있음", description="d", interest_rate=1, min_amount=100_000),
            AccountProduct(type="DEPOSIT", name="최소없음", description="d", interest_rate=1),
        ])
    tony = await make_user("ironman")
    await client.post("/accounts/checking", json={"product_id": 1}, headers=tony)
    await client.post("/dev/accounts/checking/1/charge", json={"amount": 2_000_000}, headers=tony)
    return tony


def body(product_id, amount):
    return {"product_id": product_id, "maturity_date": FUTURE, "initial_amount": amount,
            "from_checking_account_id": 1}


async def counts():
    async with SessionLocal() as db:
        return (await db.scalar(select(func.count()).select_from(DepositAccount)),
                await db.scalar(select(func.count()).select_from(TermsConsent)))


async def checking_balance(client, tony):
    return (await client.get("/accounts/checking/1", headers=tony)).json()["data"]["balance"]


async def test_exact_minimum_succeeds(client, world):
    response = await client.post("/accounts/deposit", json=body(2, 100_000), headers=world)
    assert response.status_code == 201
    assert await checking_balance(client, world) == 1_900_000


async def test_below_minimum_changes_nothing(client, world):
    before = await counts()
    response = await client.post("/accounts/deposit", json=body(2, 99_999), headers=world)
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "BELOW_MIN_AMOUNT"
    assert error["message"] == "이 상품의 최소 가입 금액은 100,000원입니다."
    assert await counts() == before
    assert await checking_balance(client, world) == 2_000_000


async def test_no_minimum_allows_one_won(client, world):
    response = await client.post("/accounts/deposit", json=body(3, 1), headers=world)
    assert response.status_code == 201


async def test_product_api_exposes_min_amount(client, world):
    rows = {p["name"]: p["min_amount"] for p in (await client.get("/products/accounts")).json()["data"]}
    assert rows == {"입출금": None, "최소있음": 100_000, "최소없음": None}
    assert (await client.get("/products/accounts/2")).json()["data"]["min_amount"] == 100_000
