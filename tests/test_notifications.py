"""Checking-account movements appear once in the owner's private in-app feed."""
import uuid

import pytest

from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.interbank.hub_client import HubReply
from avengers_bank.domains.interbank.service import interbank_service
from tests.test_interbank import hub, world

pytestmark = pytest.mark.anyio


async def unread(client, headers):
    response = await client.get("/notifications/unread-count", headers=headers)
    assert response.status_code == 200
    return response.json()["data"]["unread_count"]


async def mark_read(client, headers, through_id=None):
    if through_id is None:
        rows = (await client.get("/notifications", headers=headers)).json()["data"]
        if not rows:
            return
        through_id = rows[0]["notification_id"]
    response = await client.post("/notifications/read-all", headers=headers, json={"through_id": through_id})
    assert response.status_code == 200


async def test_transfer_notifies_both_owners_once_and_keeps_reads_private(client, world):
    tony, bruce = world["tony"], world["bruce"]
    baseline = (await client.get("/notifications", headers=tony)).json()["data"][0]["notification_id"]
    await mark_read(client, tony, baseline)
    assert await unread(client, tony) == await unread(client, bruce) == 0

    body = {"from_checking_account_id": 1, "to_account_num": world["b"]["account_num"],
            "amount": 50_000, "account_password": "1357", "request_id": str(uuid.uuid4())}
    assert (await client.post("/transfers", headers=tony, json=body)).status_code == 201
    assert (await client.post("/transfers", headers=tony, json=body)).status_code == 201
    assert await unread(client, tony) == await unread(client, bruce) == 1

    tony_items = (await client.get("/notifications", headers=tony)).json()["data"]
    bruce_items = (await client.get("/notifications", headers=bruce)).json()["data"]
    assert [item["type"] for item in tony_items if item["read_at"] is None] == ["TRANSFER_OUT"]
    assert [item["type"] for item in bruce_items if item["read_at"] is None] == ["TRANSFER_IN"]
    assert all(item["account_id"] == 2 for item in bruce_items)
    assert bruce_items[0]["amount"] == 50_000
    assert bruce_items[0]["balance_after"] == 50_000
    assert bruce_items[0]["counterpart_account"] == world["a"]["account_num"]
    assert bruce_items[0]["account_num"] == world["b"]["account_num"]

    await mark_read(client, tony, baseline)  # A transaction created after the screen loaded stays unread.
    assert await unread(client, tony) == 1
    await mark_read(client, tony)
    assert await unread(client, tony) == 0
    assert await unread(client, bruce) == 1
    assert (await client.get("/notifications")).status_code == 401


async def test_failed_transfer_does_not_notify(client, world):
    tony = world["tony"]
    await mark_read(client, tony)
    body = {"from_checking_account_id": 1, "to_account_num": world["b"]["account_num"],
            "amount": 2_000_000, "account_password": "1357"}
    assert (await client.post("/transfers", headers=tony, json=body)).status_code == 400
    assert await unread(client, tony) == 0


async def test_interbank_refund_notifies_once(client, world, hub):
    tony = world["tony"]
    await mark_read(client, tony)
    hub.mode = "timeout"
    response = await client.post("/interbank-transfers", headers=tony, json={
        "from_checking_account_id": 1, "to_bank": "902", "to_account": "110-123-0001",
        "amount": 50_000, "account_password": "1357", "request_id": str(uuid.uuid4()),
    })
    assert response.status_code == 201
    assert await unread(client, tony) == 1
    transfer_id = response.json()["data"]["transfer_id"]
    failed = HubReply(200, {"status": "FAILED", "error": "ACCOUNT_NOT_FOUND"}, True)
    async with SessionLocal() as db:
        await interbank_service.apply(db, transfer_id, failed)
    async with SessionLocal() as db:
        await interbank_service.apply(db, transfer_id, failed)
    assert await unread(client, tony) == 2
    items = (await client.get("/notifications", headers=tony)).json()["data"]
    assert [item["type"] for item in items if item["read_at"] is None] == ["INTERBANK_REFUND", "INTERBANK_OUT"]
