import pytest

from avengers_bank.core.config import Settings

pytestmark = pytest.mark.anyio

CHARGE = "/dev/accounts/checking/1/charge"


@pytest.fixture
async def headers(make_user, account_products, client):
    headers = await make_user("ironman")
    await client.post("/accounts/checking", json={"product_id": 1}, headers=headers)
    return headers


def test_dev_endpoints_are_off_by_default():
    assert Settings.model_fields["enable_dev_endpoints"].default is False


async def test_charge_adds_balance_and_records_history(client, headers):
    first = await client.post(CHARGE, json={"amount": 100_000}, headers=headers)
    assert first.status_code == 200
    assert first.json()["data"]["balance"] == 100_000

    second = await client.post(CHARGE, json={"amount": 50_000}, headers=headers)
    assert second.json()["data"]["balance"] == 150_000

    account = (await client.get("/accounts/checking/1", headers=headers)).json()["data"]
    assert account["balance"] == 150_000
    rows = (await client.get("/accounts/checking/1/histories", headers=headers)).json()["data"]
    assert [(r["type"], r["amount"], r["balance_after"]) for r in rows] == [
        ("DEV_CHARGE", 50_000, 150_000),
        ("DEV_CHARGE", 100_000, 100_000),
    ]


@pytest.mark.parametrize("amount", [0, -1, 1_000_000_000_001])
async def test_charge_rejects_invalid_amount(client, headers, amount):
    response = await client.post(CHARGE, json={"amount": amount}, headers=headers)
    assert response.status_code == 422
    assert (await client.get("/accounts/checking/1", headers=headers)).json()["data"]["balance"] == 0


async def test_charge_only_own_existing_checking_account(client, headers, make_user):
    other = await make_user("hulk")
    response = await client.post(CHARGE, json={"amount": 1000}, headers=other)
    assert (response.status_code, response.json()["error"]["code"]) == (403, "ACCOUNT_FORBIDDEN")

    response = await client.post("/dev/accounts/checking/999/charge", json={"amount": 1000}, headers=headers)
    assert (response.status_code, response.json()["error"]["code"]) == (404, "ACCOUNT_NOT_FOUND")
    assert (await client.post(CHARGE, json={"amount": 1000})).status_code == 401
    assert (await client.get("/accounts/checking/1", headers=headers)).json()["data"]["balance"] == 0
