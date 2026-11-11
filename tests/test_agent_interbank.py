"""AI 비서의 타행 이체 (C-125): 도구는 초안만, 송금은 사용자가 확인했을 때 기존 타행 이체 서비스가 한다."""

import asyncio

import httpx
import pytest

from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.agent.model_client import ModelReply
from avengers_bank.domains.agent.models import TransferDraft
from avengers_bank.domains.interbank import hub_client
from tests.test_agent import balance, chat, error_of, fake, tool, world  # noqa: F401  fixtures
from tests.test_interbank import FakeHub

pytestmark = pytest.mark.anyio

OTHER_ACCOUNT = "110-123-0001"


@pytest.fixture
def hub(monkeypatch):
    f = FakeHub()
    monkeypatch.setattr(hub_client, "_transport", httpx.MockTransport(f))
    return f


async def prepare(client, world, fake, to_bank="SimBank", amount=50_000, to_account=OTHER_ACCOUNT):
    f = fake(tool("prepare_transfer", from_account="생활비 통장", to_account_num=to_account, to_bank=to_bank, amount=amount),
             ModelReply("아래 확인 카드에서 확인해 주세요."))
    response = await chat(client, world["tony"], "심뱅크로 보내줘")
    assert response.status_code == 200, response.text
    return response.json()["data"]["action"], f


async def draft_row(draft_id):
    async with SessionLocal() as db:
        return await db.get(TransferDraft, draft_id)


async def test_prepare_interbank_creates_draft_only(client, world, fake, hub):
    action, _ = await prepare(client, world, fake, to_bank="simbank")  # 대소문자·공백이 달라도 은행을 찾는다
    assert (action["to_bank_name"], action["recipient_name"], action["amount"]) == ("SimBank", "김철수", 50_000)
    assert action["to_account_num_masked"] != OTHER_ACCOUNT  # 모델·화면에는 가린 번호
    assert action["expected_balance_after"] == 950_000
    assert hub.posts == []  # 초안 단계에서는 허브로 송금하지 않는다
    assert await balance(client, world["tony"], 1) == 1_000_000
    row = await draft_row(action["draft_id"])
    assert (row.to_bank, row.to_account_num, row.status) == ("902", OTHER_ACCOUNT, "PENDING")


async def test_confirm_sends_once_through_interbank_service(client, world, fake, hub):
    action, _ = await prepare(client, world, fake, to_bank="902")
    path = f"/agent/transfers/{action['draft_id']}/confirm"
    response = await client.post(path, headers=world["tony"])
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert (data["transfer_status"], data["to_bank_name"], data["recipient_name"], data["balance_after"]) == (
        "COMPLETED", "SimBank", "김철수", 950_000)
    assert len(hub.posts) == 1 and hub.posts[0]["to_bank"] == "902" and hub.posts[0]["amount"] == 50_000
    assert (await draft_row(action["draft_id"])).status == "EXECUTED"
    assert error_of(await client.post(path, headers=world["tony"])) == (409, "DRAFT_NOT_PENDING")
    assert len(hub.posts) == 1 and await balance(client, world["tony"], 1) == 950_000


async def test_concurrent_confirms_send_once(client, world, fake, hub):
    action, _ = await prepare(client, world, fake)
    path = f"/agent/transfers/{action['draft_id']}/confirm"
    responses = await asyncio.gather(*(client.post(path, headers=world["tony"]) for _ in range(3)))
    assert any(r.status_code == 200 for r in responses)
    assert all(r.status_code in (200, 409) for r in responses), [r.text for r in responses]
    assert await balance(client, world["tony"], 1) == 950_000  # 출금은 한 번
    assert len({p["transfer_id"] for p in hub.posts}) == 1  # 허브에도 같은 거래 하나


async def test_unknown_result_stays_pending_and_is_not_refunded(client, world, fake, hub):
    action, _ = await prepare(client, world, fake)
    hub.mode = "timeout"
    response = await client.post(f"/agent/transfers/{action['draft_id']}/confirm", headers=world["tony"])
    assert response.status_code == 200, response.text
    assert response.json()["data"]["transfer_status"] == "PENDING"
    assert await balance(client, world["tony"], 1) == 950_000  # 결과를 모르면 되돌리지 않는다 (이중 지급 방지)


async def test_confirmed_failure_refunds_and_reports(client, world, fake, hub):
    action, _ = await prepare(client, world, fake)
    hub.mode = "fail"
    response = await client.post(f"/agent/transfers/{action['draft_id']}/confirm", headers=world["tony"])
    assert error_of(response) == (404, "ACCOUNT_NOT_FOUND")
    assert await balance(client, world["tony"], 1) == 1_000_000  # 확정 실패만 환불


async def test_bank_errors_list_candidates_and_own_bank_is_same_bank_transfer(client, world, fake, hub):
    f = fake(tool("prepare_transfer", from_account="생활비 통장", to_account_num=OTHER_ACCOUNT, to_bank="없는은행", amount=1000))
    await chat(client, world["tony"], "보내줘")
    result, is_error = f.tool_result(1)
    assert is_error and result["error"]["code"] == "BANK_NOT_FOUND" and "SimBank(902)" in result["error"]["message"]

    # 우리 은행 이름을 말하면 당행 이체 초안 (허브 조회 없음)
    f = fake(tool("prepare_transfer", from_account="생활비 통장", to_account_num=world["b"]["account_num"],
                  to_bank="SpiderBank", amount=1000), ModelReply("확인해 주세요."))
    action = (await chat(client, world["tony"], "보내줘")).json()["data"]["action"]
    assert action["to_bank_name"] is None and action["recipient_name"] == "김철수"
    assert (await draft_row(action["draft_id"])).to_bank is None


async def test_to_bank_requires_full_account_number(client, world, fake, hub):
    f = fake(tool("prepare_transfer", from_account="생활비 통장", to_account="생활비 통장", to_bank="SimBank", amount=1000))
    await chat(client, world["tony"], "보내줘")
    result, is_error = f.tool_result(1)
    assert is_error and result["error"]["code"] == "INVALID_ARGUMENTS"
