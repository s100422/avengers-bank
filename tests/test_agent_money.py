"""AI 비서의 돈 관리 조회 Tool. 숫자는 money_service 값을 그대로 넘기고 사용자 본인 데이터만 본다."""

import json

import pytest

from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.agent.model_client import ModelReply
from avengers_bank.domains.agent.tools import run_tool
from avengers_bank.domains.products.models import CardProduct
from avengers_bank.domains.users.schemas import UserResponse
from tests.test_agent import fake, tool  # noqa: F401 (fixture)

pytestmark = pytest.mark.anyio

MONEY_TOOLS = ("get_spending_analysis", "get_category_spending", "get_recurring_and_schedule")


@pytest.fixture
async def world(client, make_user, account_products):
    """토니: 입출금 1번(100만 원)과 신용카드. 쿠팡 5천 원, 하이마트 50만 원(일회성), 쿠팡은 온라인쇼핑 규칙. 브루스: 입출금 2번."""
    async with SessionLocal() as db, db.begin():
        db.add(CardProduct(type="CREDIT", name="신용", description="d", credit_limit=1_000_000))
    tony, bruce = await make_user("ironman"), await make_user("hulk")
    for headers in (tony, bruce):
        await client.post("/accounts/checking", json={"product_id": 1}, headers=headers)
    await client.post("/dev/accounts/checking/1/charge", json={"amount": 1_000_000}, headers=tony)
    r = await client.post("/cards/credit", json={"product_id": 1, "payment_date": 14, "checking_account_id": 1}, headers=tony)
    assert r.status_code == 201, r.text
    for amount, place in ((5_000, "쿠팡"), (500_000, "하이마트")):
        r = await client.post("/cards/credit/1/payments", json={"place_of_use": place, "used_amount": amount}, headers=tony)
        assert r.status_code in (200, 201), r.text
    await client.put("/money/transactions/credit/1/category", json={"category": "ONLINE", "scope": "MERCHANT"}, headers=tony)
    await client.put("/money/transactions/credit/2/one-off", json={"is_one_off": True}, headers=tony)
    users = {}
    for who, h in (("tony", tony), ("bruce", bruce)):
        users[who] = UserResponse.model_validate((await client.get("/users/me", headers=h)).json()["data"])
    return {"tony": tony, "bruce": bruce, "users": users}


async def run_ok(name, args, user):
    outcome = await run_tool(name, args, user)
    assert outcome.ok, outcome.content
    assert "****" not in outcome.content  # 결제수단 라벨(카드 끝자리)은 넘기지 않는다
    return outcome.result


async def test_spending_analysis_uses_own_data(world):
    tony, bruce = world["users"]["tony"], world["users"]["bruce"]
    s = await run_ok("get_spending_analysis", {}, tony)
    assert (s.forecast.actual_to_date, s.forecast.baseline.months, s.pace_status) == (505_000, 0, "UNKNOWN")
    assert {c.category: c.actual for c in s.categories} == {"ONLINE": 5_000, "UNCLASSIFIED": 500_000}
    assert [(t.merchant, t.amount) for t in s.one_off_transactions] == [("하이마트", 500_000)]

    other = await run_ok("get_spending_analysis", {}, bruce)
    assert (other.forecast.actual_to_date, other.categories, other.one_off_transactions) == (0, [], [])


async def test_category_spending_accepts_code_or_label(world):
    tony = world["users"]["tony"]
    for category in ("ONLINE", "online", "온라인쇼핑"):
        d = await run_ok("get_category_spending", {"category": category}, tony)
        assert d.spend.actual == 5_000 and [(m.merchant, m.amount) for m in d.top_merchants] == [("쿠팡", 5_000)]
        assert [(t.merchant, t.category_source) for t in d.recent_transactions] == [("쿠팡", "RULE")]
    assert (await run_ok("get_category_spending", {"category": "ONLINE"}, world["users"]["bruce"])).recent_transactions == []
    bad = await run_tool("get_category_spending", {"category": "주식"}, tony)
    assert json.loads(bad.content)["error"]["code"] == "INVALID_ARGUMENTS"


async def test_recurring_and_schedule(client, world):
    body = {"name": "월세", "direction": "OUT", "category": "HOUSING", "amount": 550_000, "day_of_month": 31}
    assert (await client.post("/money/recurring", json=body, headers=world["tony"])).status_code == 201
    r = await run_ok("get_recurring_and_schedule", {}, world["users"]["tony"])
    assert [(i.name, i.amount, i.status) for i in r.registered] == [("월세", 550_000, "ACTIVE")]
    assert [(u.kind, u.name, u.status) for u in r.upcoming] == [("RECURRING", "월세", "ESTIMATED")]
    assert (await run_ok("get_recurring_and_schedule", {}, world["users"]["bruce"])).registered == []


async def test_rejects_user_id_and_bad_month(world):
    tony, bruce_id = world["users"]["tony"], world["users"]["bruce"].user_id
    for name in MONEY_TOOLS:
        base = {"category": "ONLINE"} if name == "get_category_spending" else {}
        for args, code in (({"user_id": bruce_id}, "INVALID_ARGUMENTS"), ({"month": "2026-13"}, "INVALID_MONTH"),
                           ({"month": "2999-01"}, "FUTURE_MONTH")):
            outcome = await run_tool(name, {**base, **args}, tony)
            assert not outcome.ok and json.loads(outcome.content)["error"]["code"] == code, (name, args)


async def test_tool_call_through_agent_loop(client, world, fake):  # noqa: F811
    def answer(turns):
        data = json.loads(turns[-1].results[0].content)
        return ModelReply(f"지금까지 {data['forecast']['actual_to_date']:,}원 썼어요.")

    f = fake(tool("get_spending_analysis"), answer)
    r = await client.post("/agent/chat", json={"message": "이번 달 소비 왜 늘었어?"}, headers=world["tony"])
    assert r.status_code == 200, r.text
    assert r.json()["data"]["answer"] == "지금까지 505,000원 썼어요."
    assert f.tool_result(1)[1] is False and "get_spending_analysis" in f.systems[0]
