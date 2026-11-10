"""돈 관리 API: 원본 거래를 중복 없이 소비로 세고, 사용자 수정이 반영되는지 (C-118)."""

import pytest

from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.money_management import service as money_service_module
from avengers_bank.domains.money_management.domain import Category
from avengers_bank.domains.money_management.router import optional_model_client
from avengers_bank.domains.products.models import CardProduct
from avengers_bank.main import app

pytestmark = pytest.mark.anyio


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


@pytest.fixture
async def world(client, make_user, account_products):
    """토니: 입출금 1·2번(1번 잔액 100만 원), 신용·체크카드. 브루스: 입출금 3번. AI 키 없음(분류는 가짜로 넣는다)."""
    async with SessionLocal() as db, db.begin():
        db.add_all([
            CardProduct(type="CREDIT", name="신용", description="d", credit_limit=1_000_000),
            CardProduct(type="DEBIT", name="체크", description="d"),
        ])
    tony, bruce = await make_user("ironman"), await make_user("hulk")
    for headers in (tony, tony, bruce):
        await client.post("/accounts/checking", json={"product_id": 1}, headers=headers)
    await client.post("/dev/accounts/checking/1/charge", json={"amount": 1_000_000}, headers=tony)
    for kind, body in (("credit", {"product_id": 1, "payment_date": 14}), ("debit", {"product_id": 2})):
        r = await client.post(f"/cards/{kind}", json={**body, "checking_account_id": 1}, headers=tony)
        assert r.status_code == 201, r.text
    app.dependency_overrides[optional_model_client] = lambda: None
    yield {"tony": tony, "bruce": bruce}
    app.dependency_overrides.pop(optional_model_client, None)


async def pay(client, headers, kind, amount, place):
    r = await client.post(f"/cards/{kind}/1/payments", json={"place_of_use": place, "used_amount": amount}, headers=headers)
    assert r.status_code in (200, 201), r.text


async def account_num(client, headers, account_id):
    return (await client.get(f"/accounts/checking/{account_id}", headers=headers)).json()["data"]["account_num"]


async def transfer(client, headers, to_num, amount):
    body = {"from_checking_account_id": 1, "to_account_num": to_num, "amount": amount}
    r = await client.post("/transfers", json=body, headers=headers)
    assert r.status_code in (200, 201), r.text


async def summary(client, headers, month=None):
    r = await client.get("/money/summary" + (f"?month={month}" if month else ""), headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_spending_counts_each_purchase_once(client, world, monkeypatch):
    tony = world["tony"]
    await pay(client, tony, "credit", 5_000, "스타벅스 강남역점")
    await pay(client, tony, "debit", 3_000, "GS25 삼성점")  # 계좌에도 CARD_PAYMENT가 남지만 한 번만 센다
    await transfer(client, tony, await account_num(client, world["bruce"], 3), 10_000)  # 남에게 이체 = 소비(이체)
    await transfer(client, tony, await account_num(client, tony, 2), 20_000)  # 내 다른 계좌 = 소비 아님

    calls = []

    async def fake_classify(names, client_):
        calls.append(sorted(names))
        return {"스타벅스": (Category.CAFE, "커피"), "gs25": (Category.MART, "편의점")}

    monkeypatch.setattr(money_service_module, "classify_merchants", fake_classify)
    app.dependency_overrides[optional_model_client] = lambda: object()
    data = await summary(client, tony)
    assert data["forecast"]["actual_to_date"] == 18_000
    assert {c["category"]: c["actual"] for c in data["categories"]} == {"CAFE": 5_000, "MART": 3_000, "TRANSFER": 10_000}
    assert data["forecast"]["baseline"]["months"] == 0 and data["pace"]["status"] == "UNKNOWN"  # 과거 데이터가 없으면 비교하지 않는다

    await summary(client, tony)
    assert len(calls) == 1  # 한 번 분류한 가맹점은 저장된 값을 쓴다


async def test_without_ai_key_merchants_stay_unclassified(client, world):
    await pay(client, world["tony"], "credit", 5_000, "어딘가 상점")
    data = await summary(client, world["tony"])
    assert [(c["category"], c["actual"]) for c in data["categories"]] == [("UNCLASSIFIED", 5_000)]
    assert data["review_count"] >= 1


async def test_category_override_and_merchant_rule(client, world):
    tony = world["tony"]
    await pay(client, tony, "credit", 5_000, "쿠팡")
    await pay(client, tony, "credit", 7_000, "쿠팡")

    r = await client.put("/money/transactions/credit/1/category", json={"category": "MART", "scope": "THIS"}, headers=tony)
    assert r.status_code == 200 and r.json()["data"]["transaction"]["category_source"] == "OVERRIDE"
    cats = {c["category"]: c["actual"] for c in (await summary(client, tony))["categories"]}
    assert cats == {"MART": 5_000, "UNCLASSIFIED": 7_000}

    r = await client.put("/money/transactions/credit/2/category", json={"category": "ONLINE", "scope": "MERCHANT"}, headers=tony)
    assert r.json()["data"]["has_merchant_rule"] is True
    cats = {c["category"]: c["actual"] for c in (await summary(client, tony))["categories"]}
    assert cats == {"MART": 5_000, "ONLINE": 7_000}  # 개별 수정은 규칙보다 앞선다

    detail = (await client.get("/money/categories/ONLINE", headers=tony)).json()["data"]
    assert [t["amount"] for t in detail["transactions"]] == [7_000]


async def test_one_off_stays_in_actual(client, world):
    tony = world["tony"]
    await pay(client, tony, "credit", 500_000, "하이마트")
    r = await client.put("/money/transactions/credit/1/one-off", json={"is_one_off": True}, headers=tony)
    assert r.json()["data"]["transaction"]["is_one_off"] is True
    data = await summary(client, tony)
    assert data["forecast"]["actual_to_date"] == 500_000
    assert [t["amount"] for t in data["one_off_transactions"]] == [500_000]


async def test_other_users_transactions_are_hidden(client, world):
    await pay(client, world["tony"], "credit", 5_000, "쿠팡")
    bruce = world["bruce"]
    assert error_of(await client.get("/money/transactions/credit/1", headers=bruce)) == (404, "TRANSACTION_NOT_FOUND")
    body = {"category": "MART", "scope": "THIS"}
    assert error_of(await client.put("/money/transactions/credit/1/category", json=body, headers=bruce)) == (404, "TRANSACTION_NOT_FOUND")
    assert (await summary(client, bruce))["forecast"]["actual_to_date"] == 0


async def test_recurring_register_update_dismiss(client, world):
    tony = world["tony"]
    r = await client.post("/money/recurring", json={"name": "월세", "direction": "OUT", "category": "HOUSING", "amount": 550_000, "day_of_month": 31}, headers=tony)
    assert r.status_code == 201, r.text
    rid = r.json()["data"]["recurring_id"]
    r = await client.patch(f"/money/recurring/{rid}", json={"status": "EXCLUDED"}, headers=tony)
    assert r.json()["data"]["status"] == "EXCLUDED"
    assert error_of(await client.patch(f"/money/recurring/{rid}", json={"amount": 1}, headers=world["bruce"])) == (404, "RECURRING_NOT_FOUND")

    r = await client.post("/money/recurring/dismiss", json={"merchant_key": "넷플릭스", "name": "넷플릭스", "direction": "OUT"}, headers=tony)
    assert r.status_code == 200
    listed = (await client.get("/money/recurring", headers=tony)).json()["data"]
    assert [i["name"] for i in listed["registered"]] == ["월세"]  # 숨긴 후보는 등록 목록에 나오지 않는다


async def test_month_validation(client, world):
    tony = world["tony"]
    assert error_of(await client.get("/money/summary?month=2999-01", headers=tony)) == (400, "FUTURE_MONTH")
    assert error_of(await client.get("/money/summary?month=2026-13", headers=tony)) == (400, "INVALID_MONTH")
    assert (await client.get("/money/summary")).status_code == 401
