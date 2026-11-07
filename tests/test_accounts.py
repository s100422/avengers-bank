from datetime import timedelta

import pytest

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.timezone import kst_start_utc, today_kst
from avengers_bank.domains.accounts.models import CheckingAccountHistory
from avengers_bank.domains.accounts.service import account_service

pytestmark = pytest.mark.anyio

FUTURE = (today_kst() + timedelta(days=365)).isoformat()
CHECKING = {"product_id": 1, "nickname": "생활비"}
DEPOSIT = {"product_id": 2, "maturity_date": FUTURE}
SAVINGS = {"product_id": 3, "monthly_payment": 100_000, "monthly_deposit_date": 25, "maturity_date": FUTURE}


@pytest.fixture
async def headers(make_user, account_products):
    return await make_user("ironman")


async def open_account(client, headers, kind, body):
    response = await client.post(f"/accounts/{kind}", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


async def test_requires_login(client):
    for method, path in [("GET", "/accounts"), ("POST", "/accounts/checking"), ("GET", "/accounts/checking/1")]:
        response = await client.request(method, path)
        assert response.status_code == 401


async def test_open_checking_with_default_limits(client, headers):
    account = await open_account(client, headers, "checking", CHECKING)
    assert account["account_type"] == "checking"
    assert account["account_num"].startswith("110-") and len(account["account_num"]) == 14
    assert account["balance"] == 0
    assert (account["per_transfer_limit"], account["daily_transfer_limit"]) == (1_000_000, 5_000_000)


async def test_open_deposit_and_savings_prefixes(client, headers):
    deposit = await open_account(client, headers, "deposit", DEPOSIT)
    savings = await open_account(client, headers, "savings", SAVINGS)
    assert deposit["account_num"].startswith("120-")
    assert savings["account_num"].startswith("220-")
    assert savings["monthly_payment"] == 100_000 and savings["monthly_deposit_date"] == 25


async def test_open_with_wrong_product_type(client, headers):
    response = await client.post("/accounts/savings", json={**SAVINGS, "product_id": 1}, headers=headers)
    assert error_of(response) == (400, "PRODUCT_TYPE_MISMATCH")


async def test_open_with_unknown_product(client, headers):
    response = await client.post("/accounts/checking", json={"product_id": 999}, headers=headers)
    assert error_of(response) == (404, "ACCOUNT_PRODUCT_NOT_FOUND")


@pytest.mark.parametrize(
    ("kind", "body"),
    [
        ("checking", {**CHECKING, "per_transfer_limit": 6_000_000}),  # 1회 > 1일(기본 500만)
        ("checking", {**CHECKING, "per_transfer_limit": 0}),
        ("deposit", {**DEPOSIT, "maturity_date": today_kst().isoformat()}),  # 오늘은 안 됨
        ("savings", {**SAVINGS, "monthly_deposit_date": 32}),
        ("savings", {**SAVINGS, "monthly_payment": -1}),
    ],
    ids=["per_over_daily", "zero_limit", "maturity_today", "deposit_date_32", "negative_payment"],
)
async def test_open_validation_errors(client, headers, kind, body):
    response = await client.post(f"/accounts/{kind}", json=body, headers=headers)
    assert response.status_code == 422


async def test_account_number_retried_on_collision(client, headers, monkeypatch):
    first = await open_account(client, headers, "checking", CHECKING)
    numbers = iter([first["account_num"], first["account_num"], "110-000-000001"])
    monkeypatch.setattr(account_service, "_new_account_num", lambda kind: next(numbers))

    second = await open_account(client, headers, "checking", CHECKING)  # 두 번 겹치고 세 번째에 성공
    assert second["account_num"] == "110-000-000001"


async def test_account_number_gives_up_after_max_attempts(client, headers, monkeypatch):
    first = await open_account(client, headers, "checking", CHECKING)
    monkeypatch.setattr(account_service, "_new_account_num", lambda kind: first["account_num"])
    response = await client.post("/accounts/checking", json=CHECKING, headers=headers)
    assert error_of(response) == (500, "ACCOUNT_NUMBER_GENERATION_FAILED")


async def test_list_only_my_accounts_across_types(client, headers, make_user):
    await open_account(client, headers, "checking", CHECKING)
    await open_account(client, headers, "deposit", DEPOSIT)
    await open_account(client, headers, "savings", SAVINGS)
    other = await make_user("hulk")
    await open_account(client, other, "checking", CHECKING)

    response = await client.get("/accounts", headers=headers)
    assert [a["account_type"] for a in response.json()["data"]] == ["checking", "deposit", "savings"]
    assert response.json()["data"][0]["nickname"] == "생활비"


async def test_get_account_detail_per_type(client, headers):
    await open_account(client, headers, "checking", CHECKING)
    await open_account(client, headers, "savings", SAVINGS)
    checking = (await client.get("/accounts/checking/1", headers=headers)).json()["data"]
    savings = (await client.get("/accounts/savings/1", headers=headers)).json()["data"]
    assert "per_transfer_limit" in checking and "maturity_date" not in checking
    assert savings["maturity_date"] == FUTURE and "per_transfer_limit" not in savings


async def test_get_account_not_found_and_forbidden(client, headers, make_user):
    await open_account(client, headers, "checking", CHECKING)
    other = await make_user("hulk")

    assert error_of(await client.get("/accounts/checking/999", headers=headers)) == (404, "ACCOUNT_NOT_FOUND")
    assert error_of(await client.get("/accounts/checking/1", headers=other)) == (404, "ACCOUNT_NOT_FOUND")
    assert (await client.get("/accounts/loan/1", headers=headers)).status_code == 422


async def test_histories_newest_first_with_paging(client, headers, make_user):
    await open_account(client, headers, "checking", CHECKING)
    async with SessionLocal() as db, db.begin():
        db.add_all([
            CheckingAccountHistory(checking_account_id=1, amount=a, balance_after=b, type=t, counterpart_account=c)
            for a, b, t, c in [
                (1000, 1000, "DEV_CHARGE", None),
                (300, 700, "TRANSFER_OUT", "110-111-222222"),
                (200, 500, "TRANSFER_OUT", None),
            ]
        ])

    rows = (await client.get("/accounts/checking/1/histories", headers=headers)).json()["data"]
    assert [r["balance_after"] for r in rows] == [500, 700, 1000]  # 최신순
    assert rows[1]["counterpart_account"] == "110-111-222222"

    page = await client.get("/accounts/checking/1/histories", params={"limit": 1, "offset": 1}, headers=headers)
    assert [r["balance_after"] for r in page.json()["data"]] == [700]
    assert (await client.get("/accounts/checking/1/histories", params={"limit": 0}, headers=headers)).status_code == 422
    other = await make_user("hulk")
    assert (await client.get("/accounts/checking/1/histories", headers=other)).status_code == 404


async def test_histories_filters(client, headers):
    await open_account(client, headers, "checking", CHECKING)
    today = today_kst()
    old = kst_start_utc(today - timedelta(days=40)) + timedelta(hours=12)  # 40일 전 정오(KST)
    async with SessionLocal() as db, db.begin():
        db.add_all([
            CheckingAccountHistory(checking_account_id=1, amount=a, balance_after=0, type=t,
                                   counterpart_account=acc, counterpart_name=name, **({"date": d} if d else {}))
            for a, t, acc, name, d in [
                (100_000, "DEV_CHARGE", None, None, old),
                (6_500, "CARD_PAYMENT", None, "스타벅스 강남점", None),
                (23_000, "CARD_PAYMENT", None, "올리브영 100%_세일", None),
                (50_000, "TRANSFER_OUT", "110-111-222222", None, None),
            ]
        ])

    async def amounts(**params):
        response = await client.get("/accounts/checking/1/histories", params=params, headers=headers)
        assert response.status_code == 200, response.text
        return sorted(r["amount"] for r in response.json()["data"])

    assert await amounts() == [6_500, 23_000, 50_000, 100_000]
    # 날짜: KST 날짜 양끝 포함
    assert await amounts(date_from=(today - timedelta(days=30)).isoformat()) == [6_500, 23_000, 50_000]
    assert await amounts(date_to=(today - timedelta(days=40)).isoformat()) == [100_000]
    assert await amounts(date_from=today.isoformat(), date_to=today.isoformat()) == [6_500, 23_000, 50_000]
    # 거래 종류 여러 개
    assert await amounts(types=["CARD_PAYMENT", "TRANSFER_OUT"]) == [6_500, 23_000, 50_000]
    # 금액 범위
    assert await amounts(min_amount=10_000, max_amount=50_000) == [23_000, 50_000]
    # 상대 이름·계좌번호 검색, 대소문자 무시, % _는 글자 그대로
    assert await amounts(q="스타벅스") == [6_500]
    assert await amounts(q="111-222") == [50_000]
    assert await amounts(q="100%_") == [23_000]
    assert await amounts(q="%") == [23_000]
    # 조건 조합
    assert await amounts(types=["CARD_PAYMENT"], min_amount=10_000) == [23_000]
    bad = await client.get("/accounts/checking/1/histories", params={"min_amount": -1}, headers=headers)
    assert bad.status_code == 422


async def test_update_nickname_and_limits(client, headers):
    await open_account(client, headers, "checking", CHECKING)
    response = await client.patch(
        "/accounts/checking/1", json={"nickname": "월급통장", "daily_transfer_limit": 3_000_000}, headers=headers
    )
    data = response.json()["data"]
    assert (data["nickname"], data["daily_transfer_limit"], data["per_transfer_limit"]) == ("월급통장", 3_000_000, 1_000_000)

    cleared = await client.patch("/accounts/checking/1", json={"nickname": None}, headers=headers)
    assert cleared.json()["data"]["nickname"] is None
    assert cleared.json()["data"]["daily_transfer_limit"] == 3_000_000  # 안 보낸 값은 그대로


async def test_update_rejects_invalid_requests(client, headers, make_user):
    await open_account(client, headers, "checking", CHECKING)
    await open_account(client, headers, "deposit", DEPOSIT)

    response = await client.patch("/accounts/checking/1", json={"per_transfer_limit": 6_000_000}, headers=headers)
    assert error_of(response) == (400, "INVALID_TRANSFER_LIMIT")
    response = await client.patch("/accounts/deposit/1", json={"per_transfer_limit": 1000}, headers=headers)
    assert error_of(response) == (400, "TRANSFER_LIMIT_NOT_SUPPORTED")
    other = await make_user("hulk")
    assert (await client.patch("/accounts/checking/1", json={"nickname": "x"}, headers=other)).status_code == 404
    # 거절된 요청은 아무것도 바꾸지 않는다
    assert (await client.get("/accounts/checking/1", headers=headers)).json()["data"]["per_transfer_limit"] == 1_000_000
