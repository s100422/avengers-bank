"""ClearingHub 연동 (docs/SPEC.md): 서명, 보내는 쪽(6절), 받는 쪽(4절).

허브는 httpx.MockTransport로 흉내 낸다. 예시 키는 SPEC 2.3의 공개된 검증 전용 값이다.
"""
import asyncio
import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.accounts.models import CheckingAccountHistory
from avengers_bank.domains.interbank import hub_client, worker
from avengers_bank.domains.interbank.models import InterbankTransfer
from avengers_bank.domains.interbank.signing import _verify, sign_request, sign_response, verify_request
from tests.conftest import (
    BANK_KEY, BANK_PUB, HUB_KEY, HUB_PUB,
)

pytestmark = pytest.mark.anyio

TID = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
OTHER_TID = "11111111-2222-4333-8444-555555555555"


def test_spec_signature_examples():
    """SPEC 2.3 예시 1·2, 2.5 예시 3과 값이 같아야 허브와 맞는다."""
    body1 = ('{"transfer_id":"7c9e6679-7425-40de-944b-e07fc1f90ae7","to_bank":"902","to_account":"110-123-0001",'
             '"from_account":"110-200-456789","amount":50000,"sender_name":"홍길동","memo":"생활비"}').encode()
    s1 = sign_request(BANK_KEY, "POST", "/v1/transfers", body1, ts="1762300800")["X-Signature"]
    assert s1 == "SY/3NCjTxAR1dC5UXHM/PkQZR9/SMa+wcDBSIrAit0jeHW5JKKgw4vZWKiN2Z7o5V+ywCY7EyWsTEfLf/F3mBw=="
    assert _verify(BANK_PUB, b"1762300800\nPOST\n/v1/transfers\n" + body1, s1)
    s2 = sign_request(HUB_KEY, "GET", f"/receive/{TID}", b"", ts="1762300800")["X-Signature"]
    assert s2 == "IMn6yCKkn/eZGPNY74b3+cNvA/4ax9knE97hh4wCQnPEHe6IEdKREh/Pit3+7bJJjx801OiRbJIvJD0HbKzPAA=="
    body3 = ('{"transfer_id":"7c9e6679-7425-40de-944b-e07fc1f90ae7","status":"COMPLETED","holder_name":"김철수",'
             '"received_at":"2026-11-05T01:20:02Z"}').encode()
    s3 = sign_response(BANK_KEY, 200, s2, body3, ts="1762300801")["X-Response-Signature"]
    assert s3 == "D84tooOZEJ6jehp/BN6dVPw1KZCB+eejxpZOqgggeTW7iJznoyNjQGEFwShbhnX7prHkg9uG9e7rP9IxZS91Dg=="


class FakeHub:
    """허브. mode로 POST /v1/transfers의 답을 고른다."""

    def __init__(self):
        self.mode = "ok"
        self.get_reply: tuple[int, dict] = (404, {"error": "TRANSFER_NOT_FOUND", "message": "없음"})
        self.posts: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        sig = request.headers["x-signature"]
        assert verify_request(BANK_PUB, request.headers["x-timestamp"], request.method, request.url.path,
                              request.content, sig), "우리가 보낸 요청 서명이 틀렸다"
        key = HUB_KEY
        if request.url.path == "/v1/banks":
            status, payload = 200, {"banks": [{"bank_code": "903", "name": "SpiderBank"}, {"bank_code": "902", "name": "SimBank"}]}
        elif request.url.path == "/v1/inquiry":
            status, payload = 200, {"to_bank": "902", "to_account": "110-123-0001", "holder_name": "김철수"}
        elif request.method == "GET":
            status, payload = self.get_reply
        else:
            self.posts.append(json.loads(request.content))
            tid = self.posts[-1]["transfer_id"]
            if self.mode == "timeout":
                raise httpx.ConnectTimeout("timeout")
            if self.mode == "5xx":
                return httpx.Response(503, content=b"<html>bad gateway</html>")
            if self.mode == "fail":
                status, payload = 404, {"error": "ACCOUNT_NOT_FOUND", "message": "받는 계좌를 찾을 수 없습니다",
                                        "transfer_id": tid, "status": "FAILED"}
            else:
                status, payload = 200, {"transfer_id": tid, "status": "COMPLETED", "holder_name": "김철수"}
                if self.mode == "badsig":
                    key = BANK_KEY  # 허브가 아닌 키로 서명한 응답
        out = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        return httpx.Response(status, content=out, headers=sign_response(key, status, sig, out))


@pytest.fixture
def hub(monkeypatch):
    fake = FakeHub()
    monkeypatch.setattr(hub_client, "_transport", httpx.MockTransport(fake))
    monkeypatch.setattr(worker, "RECENT", timedelta(0))
    monkeypatch.setattr(worker, "RESEND_AFTER", timedelta(0))
    return fake


@pytest.fixture
async def world(client, make_user, account_products):
    """토니(입출금 1번, 100만 원)와 브루스(입출금 2번, 0원)."""
    tony, bruce = await make_user("ironman"), await make_user("hulk")
    a = (await client.post("/accounts/checking", json={"product_id": 1}, headers=tony)).json()["data"]
    b = (await client.post("/accounts/checking", json={"product_id": 1}, headers=bruce)).json()["data"]
    await client.post("/dev/accounts/checking/1/charge", json={"amount": 1_000_000}, headers=tony)
    return {"tony": tony, "bruce": bruce, "a": a, "b": b}


async def send(client, world, amount=50_000, to_bank="902"):
    return await client.post("/interbank-transfers", headers=world["tony"], json={
        "from_checking_account_id": 1, "to_bank": to_bank, "to_account": "110-123-0001",
        "amount": amount, "account_password": "1357",
    })


async def balance(client, world, who="tony", account_id=1):
    return (await client.get(f"/accounts/checking/{account_id}", headers=world[who])).json()["data"]["balance"]


async def row(transfer_id):
    async with SessionLocal() as db:
        return await db.get(InterbankTransfer, transfer_id)


async def history_types(account_id=1):
    async with SessionLocal() as db:
        rows = await db.scalars(select(CheckingAccountHistory.type).where(
            CheckingAccountHistory.checking_account_id == account_id).order_by(CheckingAccountHistory.checking_account_history_id))
        return list(rows)


# ---------- 보내는 쪽 ----------

async def test_banks_excludes_own_bank_and_inquiry(client, world, hub):
    banks = (await client.get("/interbank-transfers/banks", headers=world["tony"])).json()["data"]
    assert [b["bank_code"] for b in banks] == ["902"]
    res = await client.post("/interbank-transfers/inquiry", headers=world["tony"],
                            json={"to_bank": "902", "to_account": "110-123-0001"})
    assert res.json()["data"]["holder_name"] == "김철수"
    res = await client.post("/interbank-transfers/inquiry", headers=world["tony"],
                            json={"to_bank": "903", "to_account": "x"})
    assert res.status_code == 400 and res.json()["error"]["code"] == "SAME_BANK"


async def test_send_completed(client, world, hub):
    res = await send(client, world)
    data = res.json()["data"]
    assert res.status_code == 201 and data["status"] == "COMPLETED" and data["holder_name"] == "김철수"
    assert data["to_bank_name"] == "SimBank" and data["balance_after"] == 950_000
    assert await balance(client, world) == 950_000
    assert hub.posts[0]["sender_name"] and hub.posts[0]["from_account"] == world["a"]["account_num"]
    assert await history_types() == ["DEV_CHARGE", "INTERBANK_OUT"]


async def test_send_failed_refunds(client, world, hub):
    hub.mode = "fail"
    res = await send(client, world)
    assert res.status_code == 404 and res.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"
    assert await balance(client, world) == 1_000_000
    assert await history_types() == ["DEV_CHARGE", "INTERBANK_OUT", "INTERBANK_REFUND"]
    assert (await row(hub.posts[0]["transfer_id"])).status == "FAILED"


@pytest.mark.parametrize("mode", ["timeout", "5xx", "badsig"])
async def test_unknown_result_keeps_pending_and_money_out(client, world, hub, mode):
    """타임아웃·5xx·서명이 틀린 응답은 결과를 모르는 상태다: 되돌리면 이중 지급이 된다 (SPEC 6절)."""
    hub.mode = mode
    res = await send(client, world)
    assert res.status_code == 201 and res.json()["data"]["status"] == "PENDING"
    assert await balance(client, world) == 950_000
    assert (await row(hub.posts[0]["transfer_id"])).status == "PENDING"


async def test_worker_completes_pending(client, world, hub):
    hub.mode = "timeout"
    await send(client, world)
    tid = hub.posts[0]["transfer_id"]
    hub.get_reply = (200, {"transfer_id": tid, "status": "COMPLETED", "holder_name": "김철수"})
    await worker.reconcile_once()
    assert (await row(tid)).status == "COMPLETED"
    assert await balance(client, world) == 950_000
    status = (await client.get(f"/interbank-transfers/{tid}", headers=world["tony"])).json()["data"]
    assert status["status"] == "COMPLETED"
    assert (await client.get(f"/interbank-transfers/{tid}", headers=world["bruce"])).status_code == 404  # 남의 이체


async def test_worker_refunds_failed(client, world, hub):
    hub.mode = "5xx"
    await send(client, world)
    tid = hub.posts[0]["transfer_id"]
    hub.get_reply = (200, {"transfer_id": tid, "status": "FAILED", "fail_code": "ACCOUNT_INACTIVE", "fail_message": "해지"})
    await worker.reconcile_once()
    await worker.reconcile_once()  # 두 번 돌아도 환불은 한 번
    assert await balance(client, world) == 1_000_000
    assert (await row(tid)).fail_code == "ACCOUNT_INACTIVE"
    assert (await history_types()).count("INTERBANK_REFUND") == 1


async def test_worker_resends_when_hub_has_no_record(client, world, hub):
    """조회가 404면 되돌리지 않고 같은 transfer_id로 다시 보낸다 (SPEC 3.4)."""
    hub.mode = "timeout"
    await send(client, world)
    hub.mode = "ok"
    await worker.reconcile_once()
    assert [p["transfer_id"] for p in hub.posts] == [hub.posts[0]["transfer_id"]] * 2
    assert (await row(hub.posts[0]["transfer_id"])).status == "COMPLETED"


async def test_send_checks_funds_and_limit(client, world, hub):
    res = await send(client, world, amount=2_000_000)
    assert res.status_code == 400
    assert hub.posts == [] and await balance(client, world) == 1_000_000


# ---------- 받는 쪽 ----------

def hub_request(method, path, payload=None, key=HUB_KEY, bank="000", ts=None):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode() if payload is not None else b""
    headers = {"X-Bank-Code": bank, "Content-Type": "application/json", **sign_request(key, method, path, body, ts)}
    return method, "/interbank" + path, body, headers


async def call_hub(client, *args, **kwargs):
    method, url, body, headers = hub_request(*args, **kwargs)
    return await client.request(method, url, content=body, headers=headers)


def receive_body(account_num, tid=TID, amount=30_000):
    return {"transfer_id": tid, "from_bank": "902", "from_bank_name": "SimBank", "from_account": "110-200-456789",
            "to_account": account_num, "amount": amount, "sender_name": "홍길동", "memo": "생활비"}


def assert_signed(res, request_signature):
    """응답 서명(2.5)이 허브가 검증할 수 있는 값인가: 은행 공개키로 검증한다."""
    from avengers_bank.domains.interbank.signing import verify_response
    assert verify_response(BANK_PUB, res.headers["x-response-timestamp"], res.status_code, request_signature,
                           res.content, res.headers["x-response-signature"])


async def test_receive_deposits_once_and_signs(client, world, hub):
    acct = world["b"]["account_num"]
    first = await call_hub(client, "POST", "/receive", receive_body(acct))
    assert first.status_code == 200 and first.json() == {"transfer_id": TID, "status": "COMPLETED", "holder_name": world["b"] and first.json()["holder_name"]}
    again = await call_hub(client, "POST", "/receive", receive_body(acct))  # 같은 ID: 입금하지 않고 같은 답
    assert again.status_code == 200 and again.json()["status"] == "COMPLETED"
    assert await balance(client, world, "bruce", 2) == 30_000
    assert await history_types(2) == ["INTERBANK_IN"]
    async with SessionLocal() as db:
        hist = await db.scalar(select(CheckingAccountHistory).where(CheckingAccountHistory.checking_account_id == 2))
    assert hist.counterpart_name == "SimBank 홍길동"
    sent = hub_request("POST", "/receive", receive_body(acct))
    res = await client.request(sent[0], sent[1], content=sent[2], headers=sent[3])
    assert_signed(res, sent[3]["X-Signature"])
    status = await call_hub(client, "GET", f"/receive/{TID}")
    assert status.status_code == 200 and status.json()["status"] == "COMPLETED" and "received_at" in status.json()


async def test_receive_unknown_account_is_404_and_not_recorded(client, world, hub):
    res = await call_hub(client, "POST", "/receive", receive_body("999-999-999999"))
    assert res.status_code == 404 and res.json()["error"] == "ACCOUNT_NOT_FOUND"
    assert (await row(TID)) is None
    assert (await call_hub(client, "GET", f"/receive/{TID}")).status_code == 404  # 입금하지 않은 거래는 404 (4.3)


async def test_receive_rejects_bad_signature_but_still_signs(client, world, hub):
    acct = world["b"]["account_num"]
    for kwargs in ({"key": BANK_KEY}, {"bank": "903"}, {"ts": "1762300800"}):  # 남의 키 / 허브가 아닌 코드 / 오래된 시각
        method, url, body, headers = hub_request("POST", "/receive", receive_body(acct), **kwargs)
        res = await client.request(method, url, content=body, headers=headers)
        assert res.status_code == 401 and res.json()["error"] == "SIGNATURE_INVALID"
        assert_signed(res, headers["X-Signature"])
    assert await balance(client, world, "bruce", 2) == 0
    res = await client.request("POST", "/interbank/receive", content=b"{}")  # 서명 헤더 자체가 없다
    assert res.status_code == 401


async def test_receive_validates_body(client, world, hub):
    body = receive_body(world["b"]["account_num"]) | {"amount": 0}
    res = await call_hub(client, "POST", "/receive", body)
    assert res.status_code == 422 and res.json()["error"] == "VALIDATION_ERROR"
    res = await call_hub(client, "POST", "/receive", receive_body(world["b"]["account_num"]) | {"amount": 1.5})
    assert res.status_code == 422


async def test_receive_concurrent_same_id_never_4xx(client, world, hub):
    """같은 ID가 동시에 오면 입금은 한 번, 응답에 4xx는 없다 (SPEC 4.2 규칙 2: 4xx면 이중 지급)."""
    acct = world["b"]["account_num"]
    results = await asyncio.gather(*[call_hub(client, "POST", "/receive", receive_body(acct, OTHER_TID)) for _ in range(5)])
    assert all(r.status_code in (200, 503) for r in results), [r.status_code for r in results]
    assert any(r.status_code == 200 for r in results)
    assert await balance(client, world, "bruce", 2) == 30_000
    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(InterbankTransfer).where(InterbankTransfer.direction == "IN")) == 1


async def test_inquiry_from_hub(client, world, hub):
    res = await call_hub(client, "POST", "/inquiry", {"account_num": world["b"]["account_num"]})
    assert res.status_code == 200 and res.json()["holder_name"]
    res = await call_hub(client, "POST", "/inquiry", {"account_num": "000-000-000000"})
    assert res.status_code == 404 and res.json()["error"] == "ACCOUNT_NOT_FOUND"
