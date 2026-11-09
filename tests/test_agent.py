"""AI 금융 비서 (C-070). 외부 모델은 부르지 않고 FakeClient가 정해 둔 응답을 돌려준다."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from avengers_bank.core.config import get_settings
from avengers_bank.core.database import SessionLocal
from avengers_bank.core.timezone import kst_start_utc, today_kst
from avengers_bank.domains.agent.model_client import (
    ModelError,
    ModelReply,
    ModelTimeout,
    ToolCall,
    ToolResultsTurn,
    UserTurn,
    get_model_client,
)
from avengers_bank.domains.agent.models import AgentMessage, TransferDraft
from avengers_bank.domains.agent.graph import LIMIT_TEXT, MAX_MODEL_CALLS
from avengers_bank.domains.agent.tools import run_tool
from avengers_bank.domains.cards.models import CreditCardHistory
from avengers_bank.domains.products.models import AccountProduct, CardProduct
from avengers_bank.domains.users.schemas import UserResponse
from avengers_bank.main import app
from tests.helpers import open_deposit

pytestmark = pytest.mark.anyio

FUTURE = (today_kst() + timedelta(days=365)).isoformat()


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


class FakeClient:
    """steps의 응답을 차례로 돌려준다. 예외면 던지고, 함수면 지금까지의 대화를 받아 응답을 만든다."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = []
        self.systems = []

    async def respond(self, system, turns, tools):
        self.systems.append(system)
        self.calls.append(list(turns))
        step = self.steps.pop(0) if self.steps else ModelReply("끝")
        if isinstance(step, Exception):
            raise step
        return step(turns) if callable(step) else step

    def tool_result(self, call_index: int, result_index: int = 0) -> tuple[dict, bool]:
        turn = self.calls[call_index][-1]
        assert isinstance(turn, ToolResultsTurn)
        r = turn.results[result_index]
        return json.loads(r.content), r.is_error


def tool(name, **args):
    return ModelReply("", [ToolCall(f"call_{name}", name, args)])


@pytest.fixture
def fake():
    holder = {}

    def use(*steps):
        holder["client"] = FakeClient(*steps)
        app.dependency_overrides[get_model_client] = lambda: holder["client"]
        return holder["client"]

    yield use
    app.dependency_overrides.pop(get_model_client, None)


@pytest.fixture
async def world(client, make_user, account_products):
    """토니(입출금 1번, 100만 원), 브루스(입출금 2번, 0원, 이름 김철수)."""
    tony, bruce = await make_user("ironman"), await make_user("hulk")
    a = (await client.post("/accounts/checking", json={"product_id": 1, "nickname": "생활비 통장"}, headers=tony)).json()["data"]
    b = (await client.post("/accounts/checking", json={"product_id": 1}, headers=bruce)).json()["data"]
    await client.post("/dev/accounts/checking/1/charge", json={"amount": 1_000_000}, headers=tony)
    await client.patch("/users/me", json={"name": "김철수"}, headers=bruce)
    users = {}
    for who, h in (("tony", tony), ("bruce", bruce)):
        users[who] = UserResponse.model_validate((await client.get("/users/me", headers=h)).json()["data"])
    return {"tony": tony, "bruce": bruce, "a": a, "b": b, "users": users}


async def chat(client, headers, message="질문", conversation_id=None):
    return await client.post("/agent/chat", json={"message": message, "conversation_id": conversation_id}, headers=headers)


async def balance(client, headers, account_id):
    return (await client.get(f"/accounts/checking/{account_id}", headers=headers)).json()["data"]["balance"]


# ── 인증·소유권 ───────────────────────────────────────────────────────


async def test_requires_login(client):
    for path in ("/agent/chat", "/agent/transfers/x/confirm", "/agent/transfers/x/cancel"):
        assert (await client.post(path, json={"message": "hi"})).status_code == 401


async def test_unconfigured_model_returns_503(client, world, monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", None)
    assert error_of(await chat(client, world["tony"])) == (503, "AGENT_UNAVAILABLE")


async def test_accounts_tool_answer_and_saved_conversation(client, world, fake):
    def answer(turns):
        data = json.loads(turns[-1].results[0].content)
        return ModelReply(f"계좌 {len(data['accounts'])}개, 잔액 {data['accounts'][0]['balance']:,}원입니다.")

    f = fake(tool("get_my_accounts"), answer)
    response = await chat(client, world["tony"], "내 계좌가 몇 개야?")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["answer"] == "계좌 1개, 잔액 1,000,000원입니다." and body["action"] is None

    data, is_error = f.tool_result(1)
    assert not is_error
    (item,) = data["accounts"]
    assert (item["name"], item["balance"], item["status"]) == ("생활비 통장", 1_000_000, "ACTIVE")
    full = world["a"]["account_num"]
    assert item["account_num_masked"] == f"{full[:3]}-***-**{full[-4:]}" and full not in json.dumps(data)

    async with SessionLocal() as db:
        rows = list(await db.scalars(select(AgentMessage).order_by(AgentMessage.agent_message_id)))
    assert [(r.role, r.conversation_id) for r in rows] == [("user", body["conversation_id"]), ("assistant", body["conversation_id"])]
    assert rows[1].tool_calls == [{"name": "get_my_accounts", "ok": True}]  # 원본 결과는 저장하지 않는다


async def test_conversation_continues_and_is_private(client, world, fake):
    fake(ModelReply("첫 답"))
    cid = (await chat(client, world["tony"], "첫 질문")).json()["data"]["conversation_id"]

    f = fake(ModelReply("둘째 답"))
    assert (await chat(client, world["tony"], "둘째 질문", cid)).json()["data"]["conversation_id"] == cid
    texts = [getattr(t, "text", None) or t.reply.text for t in f.calls[0]]
    assert texts == ["첫 질문", "첫 답", "둘째 질문"]  # 지난 대화를 모델에 넘긴다

    fake(ModelReply("x"))
    assert error_of(await chat(client, world["bruce"], "남의 대화", cid)) == (404, "CONVERSATION_NOT_FOUND")
    assert error_of(await chat(client, world["tony"], "없는 대화", 999)) == (404, "CONVERSATION_NOT_FOUND")


async def test_user_id_cannot_be_injected_and_other_accounts_are_hidden(client, world):
    tony = world["users"]["tony"]
    outcome = await run_tool("get_my_accounts", {"user_id": world["users"]["bruce"].user_id}, tony)
    assert not outcome.ok and json.loads(outcome.content)["error"]["code"] == "INVALID_ARGUMENTS"

    outcome = await run_tool("get_transaction_history", {"account_type": "checking", "account_id": 2}, tony)
    assert not outcome.ok and json.loads(outcome.content)["error"]["code"] == "ACCOUNT_NOT_FOUND"

    # 브루스의 계좌는 번호 끝자리로도 부를 수 없다 (내 계좌 안에서만 찾는다). 후보에는 내 계좌만 나온다
    bruce_num = world["b"]["account_num"]
    outcome = await run_tool("prepare_transfer", {"from_account": bruce_num[-4:], "to_account_num": world["a"]["account_num"], "amount": 1}, tony)
    error = json.loads(outcome.content)["error"]
    assert error["code"] == "FROM_ACCOUNT_NOT_FOUND" and "생활비 통장" in error["message"] and bruce_num not in error["message"]

    assert json.loads((await run_tool("execute_transfer", {}, tony)).content)["error"]["code"] == "UNKNOWN_TOOL"


# ── 조회 Tool ─────────────────────────────────────────────────────────


async def add_credit_card(client, headers):
    async with SessionLocal() as db, db.begin():
        db.add(CardProduct(type="CREDIT", name="신용", description="d", credit_limit=1_000_000))
    r = await client.post("/cards/credit", json={"product_id": 1, "checking_account_id": 1, "payment_date": 14}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def test_financial_summary_is_computed_by_backend(client, world):
    tony = world["tony"]
    assert (await open_deposit(client, tony, 200_000, from_id=1)).status_code == 201
    card = await add_credit_card(client, tony)
    await client.post(f"/cards/credit/{card['card_id']}/payments", json={"place_of_use": "마트", "used_amount": 300_000}, headers=tony)

    outcome = await run_tool("get_financial_summary", {}, world["users"]["tony"])
    s = outcome.result
    assert (s.active_account_count, s.total_balance, s.checking_balance, s.deposit_balance, s.savings_balance) == (
        2, 1_000_000, 800_000, 200_000, 0)
    assert (s.credit_outstanding_total, s.unpaid_bill_total) == (300_000, 0)
    assert s.next_card_payment_date is not None  # 청구서는 없지만 미결제액이 있어 다음 결제일
    (m,) = s.maturities
    assert (m.balance, m.days_left) == (200_000, 365)


async def test_transaction_history_filters(client, world):
    tony, to = world["tony"], world["b"]["account_num"]
    for amount in (30_000, 50_000):
        assert (await client.post("/transfers", json={"from_checking_account_id": 1, "to_account_num": to, "amount": amount}, headers=tony)).status_code == 201
    user = world["users"]["tony"]

    async def search(**args):
        outcome = await run_tool("get_transaction_history", args, user)
        assert outcome.ok, outcome.content
        return outcome.result

    r = await search(counterpart_name="김철수")
    assert [(t.type, t.amount) for t in r.transactions] == [("TRANSFER_OUT", 50_000), ("TRANSFER_OUT", 30_000)]
    assert r.transactions[0].counterpart_account_masked == f"{to[:3]}-***-**{to[-4:]}"
    assert [t.type for t in (await search(types=["DEV_CHARGE"])).transactions] == ["DEV_CHARGE"]
    limited = await search(limit=1)
    assert len(limited.transactions) == 1 and limited.has_more
    tomorrow = (today_kst() + timedelta(days=1)).isoformat()
    assert (await search(date_from=tomorrow)).transactions == []
    assert len((await search(account_type="checking", account_id=1, date_to=today_kst().isoformat())).transactions) == 3

    for bad in ({"limit": 51}, {"account_id": 1}, {"types": ["NOPE"]}):
        assert not (await run_tool("get_transaction_history", bad, user)).ok


async def test_card_payment_shortfall(client, world):
    tony = world["tony"]
    card = await add_credit_card(client, tony)
    this_first = today_kst().replace(day=1)
    last_start = (this_first - timedelta(days=1)).replace(day=1)
    await client.post(f"/cards/credit/{card['card_id']}/payments", json={"place_of_use": "지난달", "used_amount": 500_000}, headers=tony)
    async with SessionLocal() as db, db.begin():
        await db.execute(update(CreditCardHistory).values(time=kst_start_utc(last_start) + timedelta(hours=1)))
    bill = (await client.post(f"/cards/credit/{card['card_id']}/bills", json={"year_month": last_start.strftime("%Y-%m")}, headers=tony)).json()["data"]
    # 결제계좌 잔액을 20만 원으로 줄인다
    await client.post("/transfers", json={"from_checking_account_id": 1, "to_account_num": world["b"]["account_num"], "amount": 800_000}, headers=tony)

    s = (await run_tool("get_card_payment_status", {}, world["users"]["tony"])).result
    (c,) = s.cards
    assert (c.unpaid_bill_total, c.outstanding_amount, c.next_payment_basis) == (500_000, 500_000, "BILL")
    assert c.next_payment_date.isoformat() == bill["due_date"] and c.card_num_masked.startswith("4000-****-****-")
    (p,) = s.payment_accounts
    assert (p.name, p.balance, p.shortfall_for_unpaid_bills, p.shortfall_for_outstanding) == ("생활비 통장", 200_000, 300_000, 300_000)
    assert s.total_shortfall_for_unpaid_bills == 300_000


# ── Agent 루프 ────────────────────────────────────────────────────────


async def test_model_errors_are_reported_without_details(client, world, fake):
    fake(ModelTimeout())
    assert error_of(await chat(client, world["tony"])) == (504, "AGENT_TIMEOUT")
    fake(ModelError("secret upstream detail"))
    response = await chat(client, world["tony"])
    assert error_of(response) == (503, "AGENT_UNAVAILABLE") and "secret" not in response.text
    async with SessionLocal() as db:
        assert list(await db.scalars(select(AgentMessage))) == []  # 실패한 질문은 저장하지 않는다


async def test_tool_loop_is_capped(client, world, fake):
    f = fake(*[tool("get_my_accounts") for _ in range(MAX_MODEL_CALLS + 3)])
    response = await chat(client, world["tony"])
    assert response.json()["data"]["answer"] == LIMIT_TEXT
    assert len(f.calls) == MAX_MODEL_CALLS

    many = ModelReply("", [ToolCall(f"c{i}", "get_my_accounts", {}) for i in range(9)])
    f = fake(many)
    assert (await chat(client, world["tony"])).json()["data"]["answer"] == LIMIT_TEXT
    assert len(f.calls) == 1


# ── 이체 초안·확인 ────────────────────────────────────────────────────


async def prepare(client, world, fake, amount=50_000):
    f = fake(tool("prepare_transfer", from_account="생활비 통장", to_account_num=world["b"]["account_num"], amount=amount),
             ModelReply("아래 확인 카드에서 내용을 확인해 주세요."))
    response = await chat(client, world["tony"], f"김철수에게 {amount}원 보내줘")
    assert response.status_code == 200, response.text
    return response.json()["data"]["action"], f


async def test_prepare_transfer_only_creates_draft(client, world, fake):
    action, f = await prepare(client, world, fake)
    full = world["b"]["account_num"]
    assert action["type"] == "TRANSFER_CONFIRMATION"
    assert action["from_account_id"] == 1  # 비밀번호 안내 링크용
    assert (action["from_account_name"], action["recipient_name"], action["amount"], action["expected_balance_after"]) == (
        "생활비 통장", "김철수", 50_000, 950_000)
    assert action["to_account_num_masked"] == f"{full[:3]}-***-**{full[-4:]}" and len(action["draft_id"]) >= 40
    assert action["expires_at"].endswith(("Z", "+00:00"))
    # 돈은 움직이지 않았다
    assert await balance(client, world["tony"], 1) == 1_000_000
    assert await balance(client, world["bruce"], 2) == 0
    assert (await client.get("/accounts/checking/2/histories", headers=world["bruce"])).json()["data"] == []
    async with SessionLocal() as db:
        saved = (await db.scalars(select(AgentMessage).where(AgentMessage.role == "assistant"))).one()
    assert saved.action["draft_id"] == action["draft_id"] and full not in json.dumps(saved.action)


async def test_prepare_transfer_validation_errors(client, world, fake):
    user, own, other = world["users"]["tony"], world["a"]["account_num"], world["b"]["account_num"]
    cases = [
        ({"to_account_num": own, "amount": 1}, "SAME_ACCOUNT_TRANSFER"),
        ({"to_account_num": "110-000-000000", "amount": 1}, "ACCOUNT_NOT_FOUND"),
        ({"to_account_num": other, "amount": 1_000_001}, "INSUFFICIENT_BALANCE"),
        ({"to_account_num": other, "amount": 0}, "INVALID_ARGUMENTS"),
    ]
    for args, code in cases:
        outcome = await run_tool("prepare_transfer", {"from_account": "생활비", **args}, user)
        assert json.loads(outcome.content)["error"]["code"] == code
    await client.patch("/accounts/checking/1", json={"per_transfer_limit": 10_000}, headers=world["tony"])
    outcome = await run_tool("prepare_transfer", {"from_account": "생활비", "to_account_num": other, "amount": 10_001}, user)
    error = json.loads(outcome.content)["error"]
    assert error["code"] == "PER_TRANSFER_LIMIT_EXCEEDED" and "10,000원" in error["message"]  # 모델이 한도를 지어내지 않게 금액을 준다
    async with SessionLocal() as db:
        assert list(await db.scalars(select(TransferDraft))) == []


async def open_second(client, headers, nickname):
    return (await client.post("/accounts/checking", json={"product_id": 1, "nickname": nickname}, headers=headers)).json()["data"]


async def test_prepare_transfer_to_own_account_by_name(client, world, fake):
    """'월급 → 생활비'처럼 본인 계좌끼리는 이름만으로 초안을 만든다. 모델은 id도 번호도 모른다 (C-100)."""
    tony = world["tony"]
    second = await open_second(client, tony, "월급 통장")
    f = fake(tool("prepare_transfer", from_account="생활비 계좌", to_account="월급", amount=30_000),
             ModelReply("아래 확인 카드에서 내용을 확인해 주세요."))
    body = (await chat(client, tony, "생활비 계좌에서 월급 계좌로 3만원")).json()["data"]
    full = second["account_num"]
    assert body["action"]["from_account_name"] == "생활비 통장" and body["action"]["amount"] == 30_000
    assert body["action"]["to_account_num_masked"] == f"{full[:3]}-***-**{full[-4:]}" and full not in json.dumps(body)
    async with SessionLocal() as db:
        assert (await db.scalars(select(TransferDraft))).one().to_account_num == full  # 서버가 번호를 찾아 넣는다
    assert f.tool_result(1)[1] is False


async def test_account_reference_forms(client, world):
    """이름 표기가 달라도('월급 계좌'/'월급 통장'), 번호 끝 4자리로도 같은 계좌를 찾는다."""
    user = world["users"]["tony"]
    second = await open_second(client, world["tony"], "월급 통장")
    for ref in ("월급 통장", "월급 계좌", "월급", "  월급통장 ", second["account_num"][-4:], second["account_num"][-6:]):
        outcome = await run_tool("prepare_transfer", {"from_account": "생활비", "to_account": ref, "amount": 1}, user)
        assert outcome.ok, (ref, outcome.content)
        assert json.loads(outcome.content)["to_account_num_masked"].endswith(second["account_num"][-4:])


async def test_account_reference_errors_list_candidates_without_ids(client, world):
    user, tony = world["users"]["tony"], world["tony"]
    await open_second(client, tony, "월급 모음")
    await open_second(client, tony, "월급 저축")
    cases = [  # (인자, 오류 코드, 메시지에 있어야 할 것)
        ({"from_account": "여행", "to_account_num": world["b"]["account_num"]}, "FROM_ACCOUNT_NOT_FOUND", "생활비 통장"),
        ({"from_account": "생활비", "to_account": "여행"}, "TO_ACCOUNT_NOT_FOUND", "월급 모음"),
        ({"from_account": "생활비", "to_account": "월급"}, "ACCOUNT_AMBIGUOUS", "월급 저축"),  # 이름이 딱 맞는 계좌는 없고 둘 다 '월급' 포함
        ({"from_account": "생활비", "to_account": "생활비"}, "SAME_ACCOUNT_TRANSFER", None),
    ]
    for args, code, expected in cases:
        error = json.loads((await run_tool("prepare_transfer", {**args, "amount": 1}, user)).content)["error"]
        assert error["code"] == code, (args, error)
        if expected:
            assert expected in error["message"] and "account_id" not in error["message"], error
    for args in ({"from_account": "생활비", "amount": 1},  # 받는 계좌 없음
                 {"from_account": "생활비", "to_account": "월급 통장", "to_account_num": world["b"]["account_num"], "amount": 1},  # 둘 다 줌
                 {"from_account_id": 1, "to_account": "월급 통장", "amount": 1}):  # 옛 인자(id)는 거절
        assert json.loads((await run_tool("prepare_transfer", args, user)).content)["error"]["code"] == "INVALID_ARGUMENTS", args
    async with SessionLocal() as db:
        assert list(await db.scalars(select(TransferDraft))) == []


async def test_system_prompt_has_no_account_data(client, world, fake):
    """계좌 정보는 이체 요청 때 서버가 찾는다. 프롬프트에는 별칭도 번호도 id도 없다 (C-100)."""
    f = fake(ModelReply("답"))
    await chat(client, world["tony"])
    system = f.systems[0]
    assert "생활비 통장" not in system and "account_id=" not in system and world["a"]["account_num"] not in system


async def test_confirm_executes_once_and_records_history(client, world, fake):
    action, _ = await prepare(client, world, fake)
    path = f"/agent/transfers/{action['draft_id']}"
    assert error_of(await client.post(f"{path}/confirm", headers=world["bruce"])) == (404, "DRAFT_NOT_FOUND")

    response = await client.post(f"{path}/confirm", headers=world["tony"])
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert (data["status"], data["amount"], data["balance_after"], data["recipient_name"]) == ("EXECUTED", 50_000, 950_000, "김철수")
    assert await balance(client, world["tony"], 1) == 950_000
    assert await balance(client, world["bruce"], 2) == 50_000
    rows = (await client.get("/accounts/checking/1/histories", headers=world["tony"])).json()["data"]
    assert (rows[0]["type"], rows[0]["amount"], rows[0]["balance_after"], rows[0]["counterpart_name"]) == (
        "TRANSFER_OUT", 50_000, 950_000, "김철수")

    assert error_of(await client.post(f"{path}/confirm", headers=world["tony"])) == (409, "DRAFT_NOT_PENDING")
    assert error_of(await client.post(f"{path}/cancel", headers=world["tony"])) == (409, "DRAFT_NOT_PENDING")
    assert await balance(client, world["tony"], 1) == 950_000


async def test_concurrent_confirms_transfer_once(client, world, fake):
    action, _ = await prepare(client, world, fake)
    path = f"/agent/transfers/{action['draft_id']}/confirm"
    responses = await asyncio.gather(*(client.post(path, headers=world["tony"]) for _ in range(3)))
    assert sorted(r.status_code for r in responses) == [200, 409, 409]
    assert await balance(client, world["tony"], 1) == 950_000
    assert await balance(client, world["bruce"], 2) == 50_000


async def test_expired_draft_cannot_run(client, world, fake):
    action, _ = await prepare(client, world, fake)
    async with SessionLocal() as db, db.begin():
        await db.execute(update(TransferDraft).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    path = f"/agent/transfers/{action['draft_id']}"
    assert error_of(await client.post(f"{path}/confirm", headers=world["tony"])) == (409, "DRAFT_EXPIRED")
    async with SessionLocal() as db:
        assert (await db.get(TransferDraft, action["draft_id"])).status == "EXPIRED"
    assert error_of(await client.post(f"{path}/confirm", headers=world["tony"])) == (409, "DRAFT_NOT_PENDING")
    assert await balance(client, world["tony"], 1) == 1_000_000


async def test_confirm_rechecks_limits_and_balance(client, world, fake):
    action, _ = await prepare(client, world, fake)
    path = f"/agent/transfers/{action['draft_id']}/confirm"
    # 초안을 만든 뒤 한도를 낮추면 확인 때 다시 검사해서 막는다. 초안은 PENDING으로 남는다
    await client.patch("/accounts/checking/1", json={"per_transfer_limit": 10_000}, headers=world["tony"])
    assert error_of(await client.post(path, headers=world["tony"])) == (400, "PER_TRANSFER_LIMIT_EXCEEDED")
    await client.patch("/accounts/checking/1", json={"per_transfer_limit": 1_000_000}, headers=world["tony"])
    # 그사이 잔액이 줄어도 막는다
    await client.post("/transfers", json={"from_checking_account_id": 1, "to_account_num": world["b"]["account_num"], "amount": 980_000}, headers=world["tony"])
    assert error_of(await client.post(path, headers=world["tony"])) == (400, "INSUFFICIENT_BALANCE")
    async with SessionLocal() as db:
        assert (await db.get(TransferDraft, action["draft_id"])).status == "PENDING"
    assert await balance(client, world["tony"], 1) == 20_000


async def test_cancel_draft(client, world, fake):
    action, _ = await prepare(client, world, fake)
    path = f"/agent/transfers/{action['draft_id']}"
    assert error_of(await client.post(f"{path}/cancel", headers=world["bruce"])) == (404, "DRAFT_NOT_FOUND")
    response = await client.post(f"{path}/cancel", headers=world["tony"])
    assert response.status_code == 200 and response.json()["data"]["status"] == "CANCELLED"
    assert error_of(await client.post(f"{path}/confirm", headers=world["tony"])) == (409, "DRAFT_NOT_PENDING")
    assert await balance(client, world["tony"], 1) == 1_000_000


async def test_history_passed_to_model_is_limited(client, world, fake):
    fake(*[ModelReply(f"답{i}") for i in range(8)])
    cid = None
    for i in range(8):
        cid = (await chat(client, world["tony"], f"질문{i}", cid)).json()["data"]["conversation_id"]
    f = fake(ModelReply("마지막"))
    await chat(client, world["tony"], "마지막 질문", cid)
    turns = f.calls[0]
    assert len(turns) == 11 and isinstance(turns[0], UserTurn) and turns[0].text == "질문3"


# ── 예·적금 가입 화면 미리 채우기 (C-103) ─────────────────────────────


async def add_products():
    async with SessionLocal() as db, db.begin():
        db.add_all([
            AccountProduct(type="DEPOSIT", name="모바일 특판예금", description="d", interest_rate=3.5, min_amount=1_000_000),
            AccountProduct(type="DEPOSIT", name="청년 정기예금", description="d", interest_rate=3, min_amount=500_000),
            AccountProduct(type="SAVINGS", name="청년 도약 적금", description="d", interest_rate=4),
        ])


async def test_open_account_card_for_deposit_fills_form_without_opening(client, world, fake):
    from avengers_bank.domains.agent.tools.open_account import add_months

    await add_products()
    tony = world["tony"]
    before = (await client.get("/accounts", headers=tony)).json()["data"]
    fake(tool("prepare_open_account", kind="deposit", product="특판예금", amount=1_500_000, maturity_months=24,
              from_account="생활비", nickname="여행자금"),
         ModelReply("아래 카드에서 가입 화면으로 이어 가세요."))
    body = (await chat(client, tony, "특판예금 150만원 2년 뒤 만기로 가입하고 싶어")).json()["data"]
    action = body["action"]
    assert action["type"] == "OPEN_ACCOUNT" and (action["kind"], action["product_name"]) == ("deposit", "모바일 특판예금")
    assert action["fields"] == {
        "initial_amount": "1500000", "maturity_date": add_months(today_kst(), 24).isoformat(),  # 날짜는 서버가 계산한다
        "checking_account_id": "1", "nickname": "여행자금",
    }
    assert [(r["label"], r["value"]) for r in action["summary"]][:2] == [("상품", "모바일 특판예금"), ("가입 금액", "1,500,000원")]
    assert (await client.get("/accounts", headers=tony)).json()["data"] == before  # 가입하지 않았다
    # 대화를 다시 불러와도 카드가 그대로 읽힌다 (type으로 구분)
    messages = (await client.get(f"/agent/conversations/{body['conversation_id']}/messages", headers=tony)).json()["data"]
    assert messages[1]["action"]["type"] == "OPEN_ACCOUNT" and messages[1]["action"]["product_id"] == action["product_id"]


async def test_open_account_card_for_savings(client, world, fake):
    await add_products()
    fake(tool("prepare_open_account", kind="savings", product="도약", amount=200_000, monthly_deposit_date=15, maturity_months=12),
         ModelReply("카드를 확인해 주세요."))
    action = (await chat(client, world["tony"], "도약 적금 매월 20만원 15일")).json()["data"]["action"]
    assert (action["kind"], action["product_name"]) == ("savings", "청년 도약 적금")
    assert set(action["fields"]) == {"monthly_payment", "monthly_deposit_date", "maturity_date"}
    assert action["fields"]["monthly_payment"] == "200000" and action["fields"]["monthly_deposit_date"] == "15"


async def test_open_account_errors_return_candidates_and_never_guess(client, world):
    await add_products()
    user = world["users"]["tony"]
    soon = (today_kst() + timedelta(days=0)).isoformat()
    cases = [  # (인자, 오류 코드, 메시지에 있어야 할 것)
        ({"kind": "deposit"}, "PRODUCT_NOT_SPECIFIED", "청년 정기예금"),  # 이름이 없고 상품이 여럿
        ({"kind": "deposit", "product": "해외주식"}, "PRODUCT_NOT_FOUND", "모바일 특판예금"),
        ({"kind": "deposit", "product": "예금"}, "PRODUCT_AMBIGUOUS", "최소 1,000,000원"),  # 이름이 모두에 들어감 → 후보와 최소 금액
        ({"kind": "deposit", "product": "특판", "amount": 900_000}, "AMOUNT_BELOW_MINIMUM", "1,000,000원"),
        ({"kind": "deposit", "product": "특판", "maturity_date": soon}, "MATURITY_NOT_FUTURE", "내일"),
        ({"kind": "deposit", "product": "특판", "from_account": "여행"}, "FROM_ACCOUNT_NOT_FOUND", "생활비 통장"),
    ]
    for args, code, expected in cases:
        error = json.loads((await run_tool("prepare_open_account", args, user)).content)["error"]
        assert error["code"] == code and expected in error["message"], (args, error)
    for args in ({"kind": "deposit", "product": "특판", "maturity_months": 12, "maturity_date": FUTURE},  # 만기 둘 다
                 {"kind": "savings", "product": "도약", "monthly_deposit_date": 32},
                 {"kind": "checking", "product": "x"},  # 입출금은 이 도구로 안 다룬다
                 {"kind": "deposit", "product": "특판", "password": "1234"}):  # 비밀번호 같은 인자는 거절
        assert json.loads((await run_tool("prepare_open_account", args, user)).content)["error"]["code"] == "INVALID_ARGUMENTS", args


# ── Gemini 어댑터 (네트워크 없이 변환만 확인) ─────────────────────────


def gemini_response(*parts, finish="STOP"):
    from google.genai import types

    return types.GenerateContentResponse(candidates=[
        types.Candidate(content=types.Content(role="model", parts=list(parts)), finish_reason=finish)
    ])


async def test_gemini_client_converts_calls_and_results(monkeypatch):
    from google.genai import types

    from avengers_bank.domains.agent.model_client import AssistantTurn, GeminiModelClient, ToolResult
    from avengers_bank.domains.agent.graph import TOOL_SPECS

    gemini = GeminiModelClient("test-key", "gemini-test", timeout=5)
    sent = {}

    async def fake_generate(*, model, contents, config):
        sent.update(model=model, contents=contents, config=config)
        return gemini_response(
            types.Part(text="생각 중", thought=True),
            types.Part(function_call=types.FunctionCall(name="get_my_accounts", args={})),
        )

    monkeypatch.setattr(gemini.client.aio.models, "generate_content", fake_generate)
    reply = await gemini.respond("system", [UserTurn("내 계좌")], TOOL_SPECS)
    assert reply.text == "" and [(c.name, c.arguments) for c in reply.tool_calls] == [("get_my_accounts", {})]
    assert sent["config"].automatic_function_calling.disable  # SDK가 함수를 대신 실행하지 않는다
    assert {d.name for d in sent["config"].tools[0].function_declarations} == {s.name for s in TOOL_SPECS}

    # 결과를 돌려보낼 때: 함수 이름을 붙이고, 우리가 만든 id는 빼고, 성공은 output·실패는 error
    call = reply.tool_calls[0]
    contents = GeminiModelClient._contents([
        UserTurn("내 계좌"), AssistantTurn(reply),
        ToolResultsTurn([ToolResult(call.id, json.dumps({"accounts": []}), False)]),
    ])
    assert contents[1] is reply.raw  # 모델 원본(thought signature 포함)을 그대로 되돌려 보낸다
    fr = contents[2].parts[0].function_response
    assert (fr.name, fr.id, fr.response) == ("get_my_accounts", None, {"output": {"accounts": []}})
    err = GeminiModelClient._contents([AssistantTurn(reply), ToolResultsTurn([ToolResult(call.id, '{"error": {"code": "X"}}', True)])])
    assert err[1].parts[0].function_response.response == {"error": {"code": "X"}}


async def test_gemini_client_errors_and_blocking(monkeypatch):
    from google.genai import errors

    from avengers_bank.domains.agent.model_client import REFUSAL_TEXT, GeminiModelClient

    gemini = GeminiModelClient("test-key", "gemini-test", timeout=0.05)

    async def slow(**_):
        await asyncio.sleep(1)

    monkeypatch.setattr(gemini.client.aio.models, "generate_content", slow)
    with pytest.raises(ModelTimeout):
        await gemini.respond("s", [UserTurn("q")], [])

    async def broken(**_):
        raise errors.ServerError(500, {"error": {"message": "secret"}})

    monkeypatch.setattr(gemini.client.aio.models, "generate_content", broken)
    with pytest.raises(ModelError):
        await gemini.respond("s", [UserTurn("q")], [])

    async def blocked(**_):
        return gemini_response(finish="SAFETY")

    monkeypatch.setattr(gemini.client.aio.models, "generate_content", blocked)
    assert (await gemini.respond("s", [UserTurn("q")], [])).text == REFUSAL_TEXT
