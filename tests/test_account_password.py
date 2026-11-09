"""계좌 비밀번호 (숫자 4자리, 5회 잠금). 돈이 나가는 6곳 모두 '돈이 빠져나가는 계좌'의 비밀번호를 확인한다.

자동 첨부(BankClient.auto_account_password)는 끄고 비밀번호를 직접 보낸다.
"""

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import update

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.timezone import today_kst
from avengers_bank.domains.accounts.kinds import KINDS
from avengers_bank.domains.accounts.password import validate_account_password_format
from avengers_bank.domains.agent.tools import run_tool
from avengers_bank.domains.cards.models import CreditCard, CreditCardBill
from avengers_bank.domains.products.models import CardProduct
from avengers_bank.domains.users.schemas import UserResponse

pytestmark = pytest.mark.anyio

FUTURE = (today_kst() + timedelta(days=365)).isoformat()
TONY_PW, BRUCE_PW, SAVINGS_PW, DEPOSIT_PW = "1357", "2468", "8024", "9135"
WRONG = "0007"
FORMAT_MESSAGE = "계좌 비밀번호는 숫자 4자리이며, 같은 숫자나 연속된 숫자는 쓸 수 없습니다."


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


async def account_row(kind: str, account_id: int):
    async with SessionLocal() as db:
        return await db.get(KINDS[kind].model, account_id)


# ── 형식 규칙 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw", ["1357", "0007", "2024", "9135", "1235", "0124", "9875", "1122"])
def test_format_accepts(raw):
    assert validate_account_password_format(raw) == raw


@pytest.mark.parametrize("raw", [
    "0000", "1111", "9999",  # 같은 숫자
    "0123", "3456", "6789", "9876", "5432", "3210",  # 연속 숫자 (오름·내림)
    "123", "12345", "", "13 5", "abcd", "13a5", "１３５７", "١٣٥٧",  # 길이·문자 (전각·아랍 숫자 포함)
])
def test_format_rejects(raw):
    with pytest.raises(ValueError, match="계좌 비밀번호는 숫자 4자리"):
        validate_account_password_format(raw)


# ── 준비 ──────────────────────────────────────────────────────────────


@pytest.fixture
async def world(client, make_user, account_products):
    """토니: 입출금 1번(100만 원, 1357), 적금 1번(8024), 예금 1번(9135, 1만 원). 브루스: 입출금 2번(2468).
    신용카드 1번(토니, 결제 계좌 1번)에 미납 청구서 1번(1만 원)."""
    client.auto_account_password = False
    tony, bruce = await make_user("ironman"), await make_user("hulk")

    async def post(path, body, headers):
        response = await client.post(path, json=body, headers=headers)
        assert response.status_code in (200, 201), response.text
        return response.json()["data"]

    a = await post("/accounts/checking", {"product_id": 1, "account_password": TONY_PW}, tony)
    b = await post("/accounts/checking", {"product_id": 1, "account_password": BRUCE_PW}, bruce)
    await post(f"/dev/accounts/checking/{a['account_id']}/charge", {"amount": 1_000_000}, tony)
    await post("/accounts/savings", {
        "product_id": 3, "account_password": SAVINGS_PW, "monthly_payment": 1000,
        "monthly_deposit_date": 1, "maturity_date": FUTURE,
    }, tony)
    await post("/accounts/deposit", {
        "product_id": 2, "account_password": DEPOSIT_PW, "maturity_date": FUTURE, "initial_amount": 10_000,
        "from_checking_account_id": 1, "from_account_password": TONY_PW,
    }, tony)

    async with SessionLocal() as db, db.begin():
        db.add(CardProduct(type="CREDIT", name="신용", description="d", credit_limit=1_000_000))
    card = await post("/cards/credit", {"product_id": 1, "checking_account_id": 1, "payment_date": 14}, tony)
    async with SessionLocal() as db, db.begin():
        await db.execute(update(CreditCard).values(outstanding_amount=10_000))
        db.add(CreditCardBill(
            credit_card_id=card["card_id"], period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
            total_amount=10_000, due_date=date(2026, 2, 14),
        ))
    user = UserResponse.model_validate((await client.get("/users/me", headers=tony)).json()["data"])
    return {"tony": tony, "bruce": bruce, "a": a, "b": b, "user": user}


async def new_draft(world) -> str:
    outcome = await run_tool(
        "prepare_transfer", {"from_account": world["a"]["account_num"][-4:], "to_account_num": world["b"]["account_num"], "amount": 1000},
        world["user"],
    )
    assert outcome.ok, outcome.content
    return json.loads(outcome.content)["draft_id"]


# 돈이 나가는 6곳: (이름, 요청을 보내는 함수(client, world, password), 비밀번호를 확인하는 계좌(종류, id), 맞는 비밀번호)
async def _transfer(client, w, pw):
    body = {"from_checking_account_id": 1, "to_account_num": w["b"]["account_num"], "amount": 1000, "account_password": pw}
    return await client.post("/transfers", json=body, headers=w["tony"])


async def _savings(client, w, pw):
    body = {"from_checking_account_id": 1, "savings_account_id": 1, "amount": 1000, "account_password": pw}
    return await client.post("/transfers/savings", json=body, headers=w["tony"])


async def _deposit_open(client, w, pw):
    body = {
        "product_id": 2, "account_password": "4680", "maturity_date": FUTURE, "initial_amount": 1000,
        "from_checking_account_id": 1, "from_account_password": pw,
    }
    return await client.post("/accounts/deposit", json=body, headers=w["tony"])


async def _agent_confirm(client, w, pw):
    if "draft" not in w:
        w["draft"] = await new_draft(w)
    return await client.post(f"/agent/transfers/{w['draft']}/confirm", json={"account_password": pw}, headers=w["tony"])


async def _close(client, w, pw):
    body = {"to_checking_account_id": 1, "account_password": pw}
    return await client.post("/accounts/deposit/1/close", json=body, headers=w["tony"])


async def _bill(client, w, pw):
    return await client.post("/cards/credit/1/bills/1/payments", json={"account_password": pw}, headers=w["tony"])


SPENDS = [
    ("transfer", _transfer, ("checking", 1), TONY_PW),
    ("savings_payment", _savings, ("checking", 1), TONY_PW),
    ("deposit_open", _deposit_open, ("checking", 1), TONY_PW),
    ("agent_confirm", _agent_confirm, ("checking", 1), TONY_PW),
    ("close", _close, ("deposit", 1), DEPOSIT_PW),
    ("bill_payment", _bill, ("checking", 1), TONY_PW),
]
IDS = [s[0] for s in SPENDS]


@pytest.mark.parametrize(("name", "spend", "target", "right"), SPENDS, ids=IDS)
async def test_wrong_password_counts_and_right_one_resets(client, world, name, spend, target, right):
    for n in (1, 2):
        response = await spend(client, world, WRONG)
        assert error_of(response) == (400, "ACCOUNT_PASSWORD_INCORRECT")
        assert response.json()["error"]["message"] == f"계좌 비밀번호가 올바르지 않습니다. ({n}/5)"
        assert (await account_row(*target)).password_failed_count == n  # 롤백되지 않고 DB에 남는다

    # 다른 사람(브루스)의 비밀번호로도 안 된다
    assert error_of(await spend(client, world, BRUCE_PW)) == (400, "ACCOUNT_PASSWORD_INCORRECT")
    assert (await account_row(*target)).password_failed_count == 3

    response = await spend(client, world, right)
    assert response.status_code in (200, 201), response.text
    assert (await account_row(*target)).password_failed_count == 0


@pytest.mark.parametrize(("name", "spend", "target", "right"), SPENDS, ids=IDS)
async def test_fifth_wrong_password_locks(client, world, name, spend, target, right):
    before = (await account_row("checking", 1)).balance
    for n in range(1, 5):
        assert error_of(await spend(client, world, WRONG)) == (400, "ACCOUNT_PASSWORD_INCORRECT")
    response = await spend(client, world, WRONG)
    assert error_of(response) == (403, "ACCOUNT_PASSWORD_LOCKED")
    assert "5회" in response.json()["error"]["message"]
    row = await account_row(*target)
    assert (row.password_failed_count, row.password_locked_at is not None) == (5, True)

    # 잠긴 뒤에는 맞는 비밀번호도 403이고 돈은 움직이지 않았다
    assert error_of(await spend(client, world, right)) == (403, "ACCOUNT_PASSWORD_LOCKED")
    assert (await account_row("checking", 1)).balance == before

    # 재설정(지금은 개발용 API)이 잠금을 푼다
    kind, account_id = target
    reset = await client.post(
        f"/dev/accounts/{kind}/{account_id}/password", json={"account_password": right}, headers=world["tony"]
    )
    assert reset.status_code == 200, reset.text
    row = await account_row(*target)
    assert (row.password_failed_count, row.password_locked_at) == (0, None)
    assert (await spend(client, world, right)).status_code in (200, 201)


@pytest.mark.parametrize(("name", "spend", "target", "right"), SPENDS, ids=IDS)
async def test_unset_password_blocks_spending(client, world, name, spend, target, right):
    kind, account_id = target
    model = KINDS[kind].model
    async with SessionLocal() as db, db.begin():  # 마이그레이션 전부터 있던 계좌 = NULL
        await db.execute(update(model).where(getattr(model, KINDS[kind].id_column) == account_id).values(password_hash=None))
    assert error_of(await spend(client, world, right)) == (400, "ACCOUNT_PASSWORD_NOT_SET")


@pytest.mark.parametrize(("name", "spend", "target", "right"), SPENDS, ids=IDS)
async def test_password_is_required(client, world, name, spend, target, right):
    response = await spend(client, world, None)  # None이면 문자열이 아니라 422
    assert response.status_code == 422


async def test_cannot_spend_from_others_account_even_with_its_password(client, world):
    body = {"from_checking_account_id": 2, "to_account_num": world["a"]["account_num"], "amount": 1, "account_password": BRUCE_PW}
    assert error_of(await client.post("/transfers", json=body, headers=world["tony"])) == (404, "ACCOUNT_NOT_FOUND")
    assert (await account_row("checking", 2)).password_failed_count == 0  # 남의 계좌 실패 횟수를 올릴 수 없다


async def test_debit_card_payment_needs_no_account_password(client, world):
    async with SessionLocal() as db, db.begin():
        db.add(CardProduct(type="DEBIT", name="체크", description="d"))
    card = (await client.post("/cards/debit", json={"product_id": 2, "checking_account_id": 1}, headers=world["tony"])).json()["data"]
    response = await client.post(
        f"/cards/debit/{card['card_id']}/payments", json={"place_of_use": "편의점", "used_amount": 1000}, headers=world["tony"]
    )
    assert response.status_code == 201, response.text


# ── 개설 ──────────────────────────────────────────────────────────────


async def test_open_requires_valid_password_and_never_returns_it(client, world):
    tony = world["tony"]
    assert (await client.post("/accounts/checking", json={"product_id": 1}, headers=tony)).status_code == 422
    for bad in ("1111", "1234", "4321", "12", "abcd"):
        response = await client.post("/accounts/checking", json={"product_id": 1, "account_password": bad}, headers=tony)
        assert response.status_code == 422
        assert response.json()["error"]["details"][0]["msg"] == FORMAT_MESSAGE

    response = await client.post("/accounts/checking", json={"product_id": 1, "account_password": "2580"}, headers=tony)
    assert response.status_code == 201
    data = response.json()["data"]
    # 비밀번호 상태(password_set·password_locked, bool)만 나가고 해시·실패 횟수·원문은 나가지 않는다
    assert {k for k in data if "password" in k} == {"password_set", "password_locked"}
    for path in (f"/accounts/checking/{data['account_id']}", "/accounts"):
        text = (await client.get(path, headers=tony)).text
        assert "password_hash" not in text and "failed" not in text and "2580" not in text

    row = await account_row("checking", data["account_id"])
    assert row.password_hash.startswith("$argon2") and "2580" not in row.password_hash
    assert (row.password_failed_count, row.password_locked_at) == (0, None)
    # 예금·적금도 각자 비밀번호를 갖는다
    assert (await account_row("savings", 1)).password_hash.startswith("$argon2")
    assert (await account_row("deposit", 1)).password_hash.startswith("$argon2")


async def test_open_deposit_requires_both_passwords(client, world):
    body = {"product_id": 2, "maturity_date": FUTURE, "initial_amount": 1000, "from_checking_account_id": 1}
    tony = world["tony"]
    assert (await client.post("/accounts/deposit", json={**body, "account_password": "4680"}, headers=tony)).status_code == 422
    assert (await client.post("/accounts/deposit", json={**body, "from_account_password": TONY_PW}, headers=tony)).status_code == 422


# ── 개발용 설정 API ──────────────────────────────────────────────────


async def test_dev_set_password(client, world):
    tony, bruce = world["tony"], world["bruce"]
    assert error_of(await client.post(
        "/dev/accounts/checking/2/password", json={"account_password": "4680"}, headers=tony
    )) == (404, "ACCOUNT_NOT_FOUND")
    assert (await client.post("/dev/accounts/checking/1/password", json={"account_password": "7777"}, headers=tony)).status_code == 422

    response = await client.post("/dev/accounts/savings/1/password", json={"account_password": "4680"}, headers=tony)
    assert response.status_code == 200
    assert "password_hash" not in response.text and "4680" not in response.text
    # 적금 비밀번호가 바뀌었는지 해지로 확인: 옛 비밀번호는 틀림, 새 비밀번호로 해지된다
    close = {"to_checking_account_id": 1}
    assert error_of(await client.post(
        "/accounts/savings/1/close", json={**close, "account_password": SAVINGS_PW}, headers=tony
    )) == (400, "ACCOUNT_PASSWORD_INCORRECT")
    assert (await client.post("/accounts/savings/1/close", json={**close, "account_password": "4680"}, headers=tony)).status_code == 200
    # 브루스는 자기 계좌만 바꿀 수 있다
    assert (await client.post("/dev/accounts/checking/2/password", json={"account_password": "4680"}, headers=bruce)).status_code == 200
