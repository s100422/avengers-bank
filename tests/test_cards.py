import calendar
from datetime import timedelta

import pytest
from sqlalchemy import update

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.timezone import kst_start_utc, today_kst
from avengers_bank.domains.cards.models import CreditCardHistory
from avengers_bank.domains.cards.service import card_service
from avengers_bank.domains.products.models import CardProduct

pytestmark = pytest.mark.anyio

LIMIT = 1_000_000


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


@pytest.fixture
async def world(client, make_user, account_products):
    """토니(입출금 1번, 잔액 100만 원)와 브루스(입출금 2번). 카드 상품: 신용 1번(한도 100만 원), 체크 2번."""
    async with SessionLocal() as db, db.begin():
        db.add_all([
            CardProduct(type="CREDIT", name="신용", description="d", credit_limit=LIMIT),
            CardProduct(type="DEBIT", name="체크", description="d"),
        ])
    tony, bruce = await make_user("ironman"), await make_user("hulk")
    for headers in (tony, bruce):
        await client.post("/accounts/checking", json={"product_id": 1}, headers=headers)
    await client.post("/dev/accounts/checking/1/charge", json={"amount": 1_000_000}, headers=tony)
    return {"tony": tony, "bruce": bruce}


async def issue(client, headers, kind, account_id=1, product_id=None, **extra):
    body = {"product_id": product_id or (1 if kind == "credit" else 2), "checking_account_id": account_id}
    if kind == "credit":
        body["payment_date"] = 14
    response = await client.post(f"/cards/{kind}", json={**body, **extra}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def pay(client, headers, kind, card_id, amount, place="가맹점"):
    return await client.post(
        f"/cards/{kind}/{card_id}/payments", json={"place_of_use": place, "used_amount": amount}, headers=headers
    )


async def checking_balance(client, headers):
    return (await client.get("/accounts/checking/1", headers=headers)).json()["data"]["balance"]


async def card_amount(client, headers, kind, card_id):
    return (await client.get(f"/cards/{kind}/{card_id}", headers=headers)).json()["data"]["accumulated_amount"]


# ── 발급 ──────────────────────────────────────────────────────────────


async def test_requires_login(client):
    for method, path in [("GET", "/cards"), ("POST", "/cards/credit"), ("GET", "/cards/credit/1/bills")]:
        assert (await client.request(method, path)).status_code == 401


async def test_issue_credit_copies_product_limit(client, world):
    card = await issue(client, world["tony"], "credit")
    assert card["card_type"] == "credit"
    assert card["card_num"].startswith("4000-") and len(card["card_num"]) == 19
    assert (card["credit_limit"], card["accumulated_amount"], card["payment_date"]) == (LIMIT, 0, 14)
    assert card["checking_account_id"] == 1


async def test_issue_debit(client, world):
    card = await issue(client, world["tony"], "debit")
    assert card["card_type"] == "debit" and card["card_num"].startswith("5000-")
    assert "credit_limit" not in card


async def test_issue_errors(client, world):
    tony = world["tony"]
    body = {"product_id": 2, "checking_account_id": 1, "payment_date": 14}  # 체크 상품으로 신용카드
    assert error_of(await client.post("/cards/credit", json=body, headers=tony)) == (400, "PRODUCT_TYPE_MISMATCH")
    body = {"product_id": 999, "checking_account_id": 1}
    assert error_of(await client.post("/cards/debit", json=body, headers=tony)) == (404, "CARD_PRODUCT_NOT_FOUND")
    body = {"product_id": 2, "checking_account_id": 2}  # 남의 입출금 계좌에 연결
    assert error_of(await client.post("/cards/debit", json=body, headers=tony)) == (403, "ACCOUNT_FORBIDDEN")
    body = {"product_id": 2, "checking_account_id": 999}
    assert error_of(await client.post("/cards/debit", json=body, headers=tony)) == (404, "ACCOUNT_NOT_FOUND")
    for payment_date in (0, 32):
        body = {"product_id": 1, "checking_account_id": 1, "payment_date": payment_date}
        assert (await client.post("/cards/credit", json=body, headers=tony)).status_code == 422
    assert (await client.get("/cards", headers=tony)).json()["data"] == []  # 실패한 발급은 카드를 만들지 않는다


async def test_card_number_retried_on_collision(client, world, monkeypatch):
    first = await issue(client, world["tony"], "credit")
    numbers = iter([first["card_num"], first["card_num"], "4000-0000-0000-0001"])
    monkeypatch.setattr(card_service, "_new_card_num", lambda kind: next(numbers))
    assert (await issue(client, world["tony"], "credit"))["card_num"] == "4000-0000-0000-0001"

    monkeypatch.setattr(card_service, "_new_card_num", lambda kind: first["card_num"])
    response = await client.post(
        "/cards/credit", json={"product_id": 1, "checking_account_id": 1, "payment_date": 14}, headers=world["tony"]
    )
    assert error_of(response) == (500, "CARD_NUMBER_GENERATION_FAILED")


# ── 조회 ──────────────────────────────────────────────────────────────


async def test_list_and_detail(client, world):
    tony, bruce = world["tony"], world["bruce"]
    credit = await issue(client, tony, "credit")
    await issue(client, tony, "debit")
    await issue(client, bruce, "debit", account_id=2)

    cards = (await client.get("/cards", headers=tony)).json()["data"]
    assert [c["card_type"] for c in cards] == ["credit", "debit"]  # 내 카드만, 신용 → 체크 순
    detail = (await client.get(f"/cards/credit/{credit['card_id']}", headers=tony)).json()["data"]
    assert detail["credit_limit"] == LIMIT and "credit_limit" not in (await client.get("/cards/debit/1", headers=tony)).json()["data"]

    assert error_of(await client.get("/cards/credit/1", headers=bruce)) == (403, "CARD_FORBIDDEN")
    assert error_of(await client.get("/cards/credit/999", headers=tony)) == (404, "CARD_NOT_FOUND")
    assert (await client.get("/cards/prepaid/1", headers=tony)).status_code == 422


# ── 결제(사용) ────────────────────────────────────────────────────────


async def test_debit_payment_withdraws_from_account(client, world):
    tony = world["tony"]
    card = await issue(client, tony, "debit")
    response = await pay(client, tony, "debit", card["card_id"], 30_000, place="편의점")
    assert response.status_code == 201
    assert response.json()["data"]["accumulated_amount"] == 30_000

    assert await checking_balance(client, tony) == 970_000
    history = (await client.get("/accounts/checking/1/histories", headers=tony)).json()["data"][0]
    assert (history["type"], history["amount"], history["balance_after"]) == ("CARD_PAYMENT", 30_000, 970_000)
    rows = (await client.get(f"/cards/debit/{card['card_id']}/histories", headers=tony)).json()["data"]
    assert [(r["place_of_use"], r["used_amount"]) for r in rows] == [("편의점", 30_000)]


async def test_debit_payment_insufficient_balance_changes_nothing(client, world):
    tony = world["tony"]
    card = await issue(client, tony, "debit")
    assert error_of(await pay(client, tony, "debit", card["card_id"], 1_000_001)) == (400, "INSUFFICIENT_BALANCE")
    assert await checking_balance(client, tony) == 1_000_000
    assert await card_amount(client, tony, "debit", card["card_id"]) == 0
    assert (await client.get(f"/cards/debit/{card['card_id']}/histories", headers=tony)).json()["data"] == []


async def test_credit_payment_respects_limit_and_does_not_touch_account(client, world):
    tony = world["tony"]
    card = await issue(client, tony, "credit")
    cid = card["card_id"]
    assert (await pay(client, tony, "credit", cid, 600_000)).json()["data"]["accumulated_amount"] == 600_000
    assert error_of(await pay(client, tony, "credit", cid, 400_001)) == (400, "CREDIT_LIMIT_EXCEEDED")
    assert (await pay(client, tony, "credit", cid, 400_000)).status_code == 201  # 딱 한도까지는 허용
    assert error_of(await pay(client, tony, "credit", cid, 1)) == (400, "CREDIT_LIMIT_EXCEEDED")

    assert await checking_balance(client, tony) == 1_000_000  # 신용카드는 결제 시 돈이 나가지 않는다
    assert await card_amount(client, tony, "credit", cid) == LIMIT
    rows = (await client.get(f"/cards/credit/{cid}/histories", headers=tony)).json()["data"]
    assert [r["used_amount"] for r in rows] == [400_000, 600_000]  # 최신순


async def test_payment_validation_and_owner(client, world):
    tony, bruce = world["tony"], world["bruce"]
    card = await issue(client, tony, "debit")
    cid = card["card_id"]
    for body in ({"place_of_use": "x", "used_amount": 0}, {"place_of_use": "", "used_amount": 10},
                 {"place_of_use": "x", "used_amount": 1_000_000_000_001}):
        assert (await client.post(f"/cards/debit/{cid}/payments", json=body, headers=tony)).status_code == 422
    assert error_of(await pay(client, bruce, "debit", cid, 1000)) == (403, "CARD_FORBIDDEN")
    assert error_of(await pay(client, tony, "debit", 999, 1000)) == (404, "CARD_NOT_FOUND")
    assert await checking_balance(client, tony) == 1_000_000


# ── 신용카드 청구서 ───────────────────────────────────────────────────


def months():
    """(이번 달 1일, 지난달 1일, 지난달 말일, 지지난달 1일) — 모두 KST 기준."""
    this_first = today_kst().replace(day=1)
    last_end = this_first - timedelta(days=1)
    last_start = last_end.replace(day=1)
    prev_start = (last_start - timedelta(days=1)).replace(day=1)
    return this_first, last_start, last_end, prev_start


def ym(day):
    return day.strftime("%Y-%m")


async def backdate(place, when):
    """결제는 항상 '지금' 시각으로 기록되므로, 청구서 시험을 위해 사용 시각을 과거로 옮긴다."""
    async with SessionLocal() as db, db.begin():
        await db.execute(update(CreditCardHistory).where(CreditCardHistory.place_of_use == place).values(time=when))


async def create_bill(client, headers, card_id, year_month):
    return await client.post(f"/cards/credit/{card_id}/bills", json={"year_month": year_month}, headers=headers)


async def test_create_bill_sums_only_unbilled_usage_of_that_month(client, world):
    tony = world["tony"]
    card = await issue(client, tony, "credit", payment_date=31)
    cid = card["card_id"]
    this_first, last_start, last_end, prev_start = months()
    usage = {  # 가맹점 이름: (금액, 사용 시각)
        "지난달 초": (100_000, kst_start_utc(last_start) + timedelta(hours=12)),
        "지난달 말 23:59": (200_000, kst_start_utc(this_first) - timedelta(minutes=1)),
        "이번달 1일 00:00": (50_000, kst_start_utc(this_first)),  # 이번 달로 센다
        "지지난달": (70_000, kst_start_utc(prev_start) + timedelta(hours=1)),
    }
    for place, (amount, when) in usage.items():
        assert (await pay(client, tony, "credit", cid, amount, place=place)).status_code == 201
        await backdate(place, when)

    response = await create_bill(client, tony, cid, ym(last_start))
    assert response.status_code == 201
    bill = response.json()["data"]
    assert (bill["total_amount"], bill["status"], bill["paid_at"]) == (300_000, "UNPAID", None)
    assert (bill["period_start"], bill["period_end"]) == (last_start.isoformat(), last_end.isoformat())
    due_month = this_first  # 납부 예정일: 다음 달(=이번 달)의 결제일, 31일이 없으면 말일
    assert bill["due_date"] == due_month.replace(day=min(31, calendar.monthrange(due_month.year, due_month.month)[1])).isoformat()

    detail = (await client.get(f"/cards/credit/{cid}/bills/{bill['bill_id']}", headers=tony)).json()["data"]
    assert sorted(i["used_amount"] for i in detail["items"]) == [100_000, 200_000]

    # 지지난달 청구서에는 지지난달 사용분만 들어가고, 이미 청구된 내역은 다시 청구되지 않는다
    older = (await create_bill(client, tony, cid, ym(prev_start))).json()["data"]
    assert older["total_amount"] == 70_000
    bills = (await client.get(f"/cards/credit/{cid}/bills", headers=tony)).json()["data"]
    assert [b["period_start"] for b in bills] == [last_start.isoformat(), prev_start.isoformat()]  # 최신순
    # 청구서를 만들어도 미결제액은 그대로다 (납부할 때 줄어든다)
    assert await card_amount(client, tony, "credit", cid) == 420_000


async def test_create_bill_errors(client, world):
    tony, bruce = world["tony"], world["bruce"]
    card = await issue(client, tony, "credit")
    cid = card["card_id"]
    this_first, last_start, _, _ = months()
    await pay(client, tony, "credit", cid, 10_000, place="지난달 것")
    await backdate("지난달 것", kst_start_utc(last_start) + timedelta(hours=1))

    assert error_of(await create_bill(client, tony, cid, ym(today_kst()))) == (400, "BILLING_PERIOD_NOT_ENDED")
    assert error_of(await create_bill(client, tony, cid, "2000-01")) == (400, "NO_UNBILLED_USAGE")
    assert error_of(await create_bill(client, bruce, cid, ym(last_start))) == (403, "CARD_FORBIDDEN")
    assert error_of(await create_bill(client, tony, 999, ym(last_start))) == (404, "CARD_NOT_FOUND")
    for bad in ("2026-13", "2026-1", "abcd-ef", "0000-01"):
        assert (await create_bill(client, tony, cid, bad)).status_code == 422

    assert (await create_bill(client, tony, cid, ym(last_start))).status_code == 201
    assert error_of(await create_bill(client, tony, cid, ym(last_start))) == (409, "BILL_ALREADY_EXISTS")


async def billed_card(client, headers, usage=(300_000, 200_000)):
    """신용카드를 발급하고 지난달에 usage만큼 쓴 뒤 청구서를 만든다. (카드, 청구서)를 돌려준다."""
    card = await issue(client, headers, "credit")
    _, last_start, _, _ = months()
    for i, amount in enumerate(usage):
        await pay(client, headers, "credit", card["card_id"], amount, place=f"사용{i}")
        await backdate(f"사용{i}", kst_start_utc(last_start) + timedelta(hours=i + 1))
    bill = (await create_bill(client, headers, card["card_id"], ym(last_start))).json()["data"]
    return card, bill


async def test_pay_bill_withdraws_and_restores_limit(client, world):
    tony = world["tony"]
    card, bill = await billed_card(client, tony)
    cid, path = card["card_id"], f"/cards/credit/{card['card_id']}/bills/{bill['bill_id']}"

    response = await client.post(f"{path}/payments", headers=tony)
    assert response.status_code == 200
    paid = response.json()["data"]
    assert (paid["status"], paid["total_amount"]) == ("PAID", 500_000) and paid["paid_at"] is not None

    assert await checking_balance(client, tony) == 500_000
    history = (await client.get("/accounts/checking/1/histories", headers=tony)).json()["data"][0]
    assert (history["type"], history["amount"], history["balance_after"], history["counterpart_account"]) == (
        "CARD_BILL_PAYMENT", 500_000, 500_000, card["card_num"])
    assert await card_amount(client, tony, "credit", cid) == 0  # 갚은 만큼 한도가 돌아온다

    assert error_of(await client.post(f"{path}/payments", headers=tony)) == (409, "BILL_ALREADY_PAID")
    assert await checking_balance(client, tony) == 500_000  # 두 번째 납부는 돈을 더 내지 않는다
    assert (await pay(client, tony, "credit", cid, LIMIT)).status_code == 201  # 한도 전체를 다시 쓸 수 있다
    assert error_of(await pay(client, tony, "credit", cid, 1)) == (400, "CREDIT_LIMIT_EXCEEDED")


async def test_pay_bill_insufficient_balance_keeps_bill_unpaid(client, world):
    tony, bruce = world["tony"], world["bruce"]
    card, bill = await billed_card(client, tony)
    bruce_account = (await client.get("/accounts/checking/2", headers=bruce)).json()["data"]["account_num"]
    moved = await client.post(
        "/transfers", json={"from_checking_account_id": 1, "to_account_num": bruce_account, "amount": 800_000}, headers=tony
    )
    assert moved.status_code == 201  # 잔액 20만 원만 남김

    path = f"/cards/credit/{card['card_id']}/bills/{bill['bill_id']}"
    assert error_of(await client.post(f"{path}/payments", headers=tony)) == (400, "INSUFFICIENT_BALANCE")
    assert (await client.get(path, headers=tony)).json()["data"]["status"] == "UNPAID"
    assert await checking_balance(client, tony) == 200_000
    assert await card_amount(client, tony, "credit", card["card_id"]) == 500_000


async def test_bill_owner_and_card_mismatch(client, world):
    tony, bruce = world["tony"], world["bruce"]
    card, bill = await billed_card(client, tony)
    other = await issue(client, tony, "credit")  # 같은 사람의 다른 카드
    bid, cid = bill["bill_id"], card["card_id"]

    for method, path in [("GET", f"/cards/credit/{cid}/bills"), ("GET", f"/cards/credit/{cid}/bills/{bid}"),
                         ("POST", f"/cards/credit/{cid}/bills/{bid}/payments")]:
        assert error_of(await client.request(method, path, headers=bruce)) == (403, "CARD_FORBIDDEN")
    # 다른 카드의 청구서 번호로는 조회·납부할 수 없다
    for method, suffix in [("GET", ""), ("POST", "/payments")]:
        response = await client.request(method, f"/cards/credit/{other['card_id']}/bills/{bid}{suffix}", headers=tony)
        assert error_of(response) == (404, "BILL_NOT_FOUND")
    assert error_of(await client.get(f"/cards/credit/{cid}/bills/999", headers=tony)) == (404, "BILL_NOT_FOUND")
    assert await checking_balance(client, tony) == 1_000_000
