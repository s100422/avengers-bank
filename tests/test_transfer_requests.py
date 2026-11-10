"""A browser retry represents the same payment instruction, even after its response is lost."""
import asyncio
import uuid

import pytest
from sqlalchemy import select

from avengers_bank.core.database import SessionLocal, engine
from avengers_bank.domains.accounts.models import CheckingAccountHistory
from avengers_bank.domains.interbank.hub_client import HubReply
from avengers_bank.domains.interbank.service import interbank_service
from tests.test_interbank import balance, hub, world

pytestmark = pytest.mark.anyio


async def test_own_transfer_retry_and_changed_payload(client, world):
    rid = str(uuid.uuid4())
    body = {"from_checking_account_id": 1, "to_account_num": world["b"]["account_num"],
            "amount": 50_000, "account_password": "1357", "request_id": rid}
    first = await client.post("/transfers", headers=world["tony"], json=body)
    second = await client.post("/transfers", headers=world["tony"], json=body)
    assert first.status_code == second.status_code == 201
    assert first.json()["data"] == second.json()["data"]
    assert await balance(client, world) == 950_000
    mismatch = await client.post("/transfers", headers=world["tony"], json={**body, "amount": 70_000})
    assert mismatch.status_code == 409


async def test_interbank_retry_does_not_call_hub_twice(client, world, hub):
    rid = str(uuid.uuid4())
    body = {"from_checking_account_id": 1, "to_bank": "902", "to_account": "110-123-0001",
            "amount": 50_000, "account_password": "1357", "request_id": rid}
    first = await client.post("/interbank-transfers", headers=world["tony"], json=body)
    second = await client.post("/interbank-transfers", headers=world["tony"], json=body)
    assert first.status_code == second.status_code == 201
    assert first.json()["data"]["transfer_id"] == second.json()["data"]["transfer_id"] == rid
    assert await balance(client, world) == 950_000
    assert len(hub.posts) == 1
    mismatch = await client.post("/interbank-transfers", headers=world["tony"], json={**body, "amount": 70_000})
    assert mismatch.status_code == 409


async def test_interbank_completion_only_names_its_history(client, world, hub):
    hub.mode = "timeout"
    body = {"from_checking_account_id": 1, "to_account": "110-123-0001",
            "amount": 50_000, "account_password": "1357"}
    one = await client.post("/interbank-transfers", headers=world["tony"],
                            json={**body, "to_bank": "901", "request_id": str(uuid.uuid4())})
    two = await client.post("/interbank-transfers", headers=world["tony"],
                            json={**body, "to_bank": "902", "request_id": str(uuid.uuid4())})
    assert one.status_code == two.status_code == 201
    async with SessionLocal() as db:
        await interbank_service.apply(db, two.json()["data"]["transfer_id"],
                                      HubReply(200, {"status": "COMPLETED", "holder_name": "김철수"}, True))
    async with SessionLocal() as db:
        rows = list(await db.scalars(select(CheckingAccountHistory).where(
            CheckingAccountHistory.type == "INTERBANK_OUT").order_by(CheckingAccountHistory.checking_account_history_id)))
    assert [r.counterpart_name for r in rows] == [None, "김철수"]
    assert [r.transfer_id for r in rows] == [one.json()["data"]["transfer_id"], two.json()["data"]["transfer_id"]]


async def test_other_user_cannot_read_or_replay_request(client, world, hub):
    own_id, hub_id = str(uuid.uuid4()), str(uuid.uuid4())
    own_body = {"from_checking_account_id": 1, "to_account_num": world["b"]["account_num"],
                "amount": 10_000, "account_password": "1357", "request_id": own_id}
    hub_body = {"from_checking_account_id": 1, "to_bank": "902", "to_account": "110-123-0001",
                "amount": 10_000, "account_password": "1357", "request_id": hub_id}
    assert (await client.post("/transfers", headers=world["tony"], json=own_body)).status_code == 201
    assert (await client.post("/interbank-transfers", headers=world["tony"], json=hub_body)).status_code == 201

    assert (await client.get(f"/transfers/requests/{own_id}", headers=world["bruce"])).status_code == 404
    assert (await client.get(f"/interbank-transfers/{hub_id}", headers=world["bruce"])).status_code == 404
    assert (await client.post("/transfers", headers=world["bruce"], json=own_body)).status_code == 404
    assert (await client.post("/interbank-transfers", headers=world["bruce"], json=hub_body)).status_code == 404


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="FOR UPDATE requires PostgreSQL")
async def test_parallel_same_interbank_request_debits_once(client, world, hub):
    rid = str(uuid.uuid4())
    body = {"from_checking_account_id": 1, "to_bank": "902", "to_account": "110-123-0001",
            "amount": 50_000, "account_password": "1357", "request_id": rid}
    responses = await asyncio.gather(*[
        client.post("/interbank-transfers", headers=world["tony"], json=body) for _ in range(2)
    ])
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert len(hub.posts) == 1
    assert await balance(client, world) == 950_000


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="FOR UPDATE requires PostgreSQL")
async def test_parallel_same_own_request_debits_once(client, world):
    body = {"from_checking_account_id": 1, "to_account_num": world["b"]["account_num"],
            "amount": 50_000, "account_password": "1357", "request_id": str(uuid.uuid4())}
    responses = await asyncio.gather(*[
        client.post("/transfers", headers=world["tony"], json=body) for _ in range(2)
    ])
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert await balance(client, world) == 950_000
