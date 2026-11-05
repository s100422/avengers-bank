from datetime import timedelta

import pytest

from sqlalchemy import update

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.timezone import today_kst, today_start_utc
from avengers_bank.domains.accounts.kinds import KINDS
from avengers_bank.domains.accounts.models import CheckingAccountHistory

pytestmark = pytest.mark.anyio

FUTURE = (today_kst() + timedelta(days=365)).isoformat()


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


@pytest.fixture
async def world(client, make_user, account_products):
    """토니(입출금 1번, 잔액 100만 원)와 브루스(입출금 2번, 잔액 0)."""
    tony, bruce = await make_user("ironman"), await make_user("hulk")
    a = (await client.post("/accounts/checking", json={"product_id": 1}, headers=tony)).json()["data"]
    b = (await client.post("/accounts/checking", json={"product_id": 1}, headers=bruce)).json()["data"]
    await client.post("/dev/accounts/checking/1/charge", json={"amount": 1_000_000}, headers=tony)
    return {"tony": tony, "bruce": bruce, "a": a, "b": b}


async def balance(client, headers, kind, account_id):
    return (await client.get(f"/accounts/{kind}/{account_id}", headers=headers)).json()["data"]["balance"]


async def histories(client, headers, kind, account_id):
    rows = (await client.get(f"/accounts/{kind}/{account_id}/histories", headers=headers)).json()["data"]
    return [(r["type"], r["amount"], r["balance_after"], r["counterpart_account"]) for r in rows]


def transfer_body(world, amount, to=None):
    return {"from_checking_account_id": 1, "to_account_num": to or world["b"]["account_num"], "amount": amount}


async def test_transfer_moves_money_and_records_both_sides(client, world):
    response = await client.post("/transfers", json=transfer_body(world, 300_000), headers=world["tony"])
    assert response.status_code == 201
    assert response.json()["data"] == {
        "from_account_num": world["a"]["account_num"], "to_account_num": world["b"]["account_num"],
        "amount": 300_000, "balance_after": 700_000,
    }
    assert await balance(client, world["tony"], "checking", 1) == 700_000
    assert await balance(client, world["bruce"], "checking", 2) == 300_000

    assert (await histories(client, world["tony"], "checking", 1))[0] == (
        "TRANSFER_OUT", 300_000, 700_000, world["b"]["account_num"])
    assert await histories(client, world["bruce"], "checking", 2) == [
        ("TRANSFER_IN", 300_000, 300_000, world["a"]["account_num"])]


async def test_insufficient_balance_changes_nothing(client, world):
    response = await client.post("/transfers", json=transfer_body(world, 1_000_001), headers=world["tony"])
    assert error_of(response) == (400, "INSUFFICIENT_BALANCE")
    assert await balance(client, world["tony"], "checking", 1) == 1_000_000
    assert await balance(client, world["bruce"], "checking", 2) == 0
    assert await histories(client, world["bruce"], "checking", 2) == []


async def test_per_transfer_limit(client, world):
    await client.patch("/accounts/checking/1", json={"per_transfer_limit": 100_000}, headers=world["tony"])
    response = await client.post("/transfers", json=transfer_body(world, 100_001), headers=world["tony"])
    assert error_of(response) == (400, "PER_TRANSFER_LIMIT_EXCEEDED")
    assert (await client.post("/transfers", json=transfer_body(world, 100_000), headers=world["tony"])).status_code == 201


async def test_daily_limit_accumulates(client, world):
    await client.patch(
        "/accounts/checking/1", json={"per_transfer_limit": 200_000, "daily_transfer_limit": 500_000},
        headers=world["tony"],
    )
    for amount in (200_000, 200_000):
        assert (await client.post("/transfers", json=transfer_body(world, amount), headers=world["tony"])).status_code == 201
    over = await client.post("/transfers", json=transfer_body(world, 200_000), headers=world["tony"])
    assert error_of(over) == (400, "DAILY_LIMIT_EXCEEDED")
    exact = await client.post("/transfers", json=transfer_body(world, 100_000), headers=world["tony"])  # 합계가 딱 한도
    assert exact.status_code == 201
    assert (await client.post("/transfers", json=transfer_body(world, 1), headers=world["tony"])).status_code == 400


async def test_daily_limit_counts_only_todays_outgoing_transfers(client, world):
    """어제(KST) 나간 이체, 들어온 돈, 적금 납입은 오늘 한도에 세지 않는다."""
    await client.patch(
        "/accounts/checking/1", json={"per_transfer_limit": 500_000, "daily_transfer_limit": 500_000},
        headers=world["tony"],
    )
    start = today_start_utc()
    async with SessionLocal() as db, db.begin():
        db.add_all([
            CheckingAccountHistory(checking_account_id=1, amount=450_000, balance_after=0, type=t, date=d)
            for t, d in [
                ("TRANSFER_OUT", start - timedelta(minutes=1)),  # 어제 23:59 KST
                ("TRANSFER_IN", start + timedelta(minutes=1)),
                ("TO_SAVINGS", start + timedelta(minutes=1)),
            ]
        ])
    assert (await client.post("/transfers", json=transfer_body(world, 500_000), headers=world["tony"])).status_code == 201
    # 방금 보낸 오늘 이체는 센다: 한도(50만)를 다 썼으니 1원도 더 못 보낸다
    assert error_of(await client.post("/transfers", json=transfer_body(world, 1), headers=world["tony"])) == (400, "DAILY_LIMIT_EXCEEDED")


async def test_daily_limit_boundary_is_midnight_kst(client, world):
    """오늘 00:00 KST 정각에 나간 이체는 오늘로 세고, 1분 전(어제)은 세지 않는다."""
    await client.patch(
        "/accounts/checking/1", json={"per_transfer_limit": 500_000, "daily_transfer_limit": 500_000},
        headers=world["tony"],
    )
    start = today_start_utc()
    async with SessionLocal() as db, db.begin():
        db.add_all([
            CheckingAccountHistory(checking_account_id=1, amount=450_000, balance_after=0, type="TRANSFER_OUT", date=d)
            for d in (start - timedelta(minutes=1), start)
        ])
    # 오늘로 세는 것은 450,000원(정각 것)뿐이다. 남은 한도는 50,000원.
    over = await client.post("/transfers", json=transfer_body(world, 50_001), headers=world["tony"])
    assert error_of(over) == (400, "DAILY_LIMIT_EXCEEDED")
    assert (await client.post("/transfers", json=transfer_body(world, 50_000), headers=world["tony"])).status_code == 201


async def test_transfer_target_and_owner_errors(client, world):
    tony, bruce = world["tony"], world["bruce"]
    own_num = world["a"]["account_num"]

    assert error_of(await client.post("/transfers", json=transfer_body(world, 1000, to=own_num), headers=tony)) == (400, "SAME_ACCOUNT_TRANSFER")
    assert error_of(await client.post("/transfers", json=transfer_body(world, 1000, to="110-000-000000"), headers=tony)) == (404, "ACCOUNT_NOT_FOUND")
    # 예금·적금 번호는 입출금 이체의 받는 계좌가 될 수 없다
    deposit = (await client.post("/accounts/deposit", json={"product_id": 2, "maturity_date": FUTURE}, headers=bruce)).json()["data"]
    assert error_of(await client.post("/transfers", json=transfer_body(world, 1000, to=deposit["account_num"]), headers=tony)) == (404, "ACCOUNT_NOT_FOUND")
    # 남의 계좌에서 보내기 / 없는 계좌에서 보내기
    assert error_of(await client.post("/transfers", json=transfer_body(world, 1000), headers=bruce)) == (404, "ACCOUNT_NOT_FOUND")
    missing = {**transfer_body(world, 1000), "from_checking_account_id": 999}
    assert error_of(await client.post("/transfers", json=missing, headers=tony)) == (404, "ACCOUNT_NOT_FOUND")
    assert await balance(client, tony, "checking", 1) == 1_000_000


@pytest.mark.parametrize("amount", [0, -5, 1_000_000_000_001])
async def test_transfer_amount_validation(client, world, amount):
    response = await client.post("/transfers", json=transfer_body(world, amount), headers=world["tony"])
    assert response.status_code == 422


async def test_requires_login(client, world):
    for path in ("/transfers", "/transfers/savings", "/transfers/deposit"):
        assert (await client.post(path, json={})).status_code == 401


async def test_pay_savings(client, world):
    tony, bruce = world["tony"], world["bruce"]
    body = {"product_id": 3, "monthly_payment": 100_000, "monthly_deposit_date": 25, "maturity_date": FUTURE}
    savings = (await client.post("/accounts/savings", json=body, headers=tony)).json()["data"]

    response = await client.post(
        "/transfers/savings", json={"from_checking_account_id": 1, "savings_account_id": 1, "amount": 100_000}, headers=tony
    )
    assert response.status_code == 201
    assert response.json()["data"]["balance_after"] == 900_000
    assert await balance(client, tony, "savings", 1) == 100_000
    assert (await histories(client, tony, "checking", 1))[0] == ("TO_SAVINGS", 100_000, 900_000, savings["account_num"])
    assert await histories(client, tony, "savings", 1) == [("TRANSFER_IN", 100_000, 100_000, world["a"]["account_num"])]

    too_much = {"from_checking_account_id": 1, "savings_account_id": 1, "amount": 900_001}
    assert error_of(await client.post("/transfers/savings", json=too_much, headers=tony)) == (400, "INSUFFICIENT_BALANCE")
    # 남의 적금 계좌에는 넣을 수 없다
    other = (await client.post("/accounts/savings", json=body, headers=bruce)).json()["data"]
    assert other["account_id"] == 2
    forbidden = {"from_checking_account_id": 1, "savings_account_id": 2, "amount": 1000}
    assert error_of(await client.post("/transfers/savings", json=forbidden, headers=tony)) == (404, "ACCOUNT_NOT_FOUND")
    missing = {"from_checking_account_id": 1, "savings_account_id": 99, "amount": 1000}
    assert error_of(await client.post("/transfers/savings", json=missing, headers=tony)) == (404, "ACCOUNT_NOT_FOUND")
    assert await balance(client, tony, "checking", 1) == 900_000


async def test_pay_deposit(client, world):
    tony, bruce = world["tony"], world["bruce"]
    deposit = (await client.post("/accounts/deposit", json={"product_id": 2, "maturity_date": FUTURE}, headers=tony)).json()["data"]

    response = await client.post(
        "/transfers/deposit", json={"from_checking_account_id": 1, "deposit_account_id": 1, "amount": 400_000}, headers=tony
    )
    assert response.status_code == 201
    assert await balance(client, tony, "deposit", 1) == 400_000
    assert await balance(client, tony, "checking", 1) == 600_000
    assert (await histories(client, tony, "checking", 1))[0] == ("TO_DEPOSIT", 400_000, 600_000, deposit["account_num"])
    assert await histories(client, tony, "deposit", 1) == [("TRANSFER_IN", 400_000, 400_000, world["a"]["account_num"])]

    # 남이 내 예금에 넣을 수 없고, 내 계좌가 아닌 곳에서 보낼 수도 없다
    stolen = {"from_checking_account_id": 1, "deposit_account_id": 1, "amount": 1000}
    assert error_of(await client.post("/transfers/deposit", json=stolen, headers=bruce)) == (404, "ACCOUNT_NOT_FOUND")


@pytest.mark.parametrize("kind, path, key", [("deposit", "deposit", "deposit_account_id"), ("savings", "savings", "savings_account_id")])
async def test_payment_rejected_from_maturity_day(client, world, kind, path, key):
    tony = world["tony"]
    body = {
        "deposit": {"product_id": 2, "maturity_date": FUTURE},
        "savings": {"product_id": 3, "monthly_payment": 100_000, "monthly_deposit_date": 25, "maturity_date": FUTURE},
    }[kind]
    await client.post(f"/accounts/{kind}", json=body, headers=tony)
    pay = {"from_checking_account_id": 1, key: 1, "amount": 1000}

    async def set_maturity(day):
        async with SessionLocal() as db, db.begin():
            await db.execute(update(KINDS[kind].model).values(maturity_date=day))

    await set_maturity(today_kst())  # 만기일 당일부터 거절
    assert error_of(await client.post(f"/transfers/{path}", json=pay, headers=tony)) == (400, "ACCOUNT_MATURED")
    assert await balance(client, tony, "checking", 1) == 1_000_000

    await set_maturity(today_kst() + timedelta(days=1))  # 만기 전날까지는 가능
    assert (await client.post(f"/transfers/{path}", json=pay, headers=tony)).status_code == 201
