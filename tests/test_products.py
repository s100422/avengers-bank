import pytest

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.exceptions import BadRequestException, NotFoundException
from avengers_bank.domains.products.models import AccountProduct, CardProduct
from avengers_bank.domains.products.service import product_service

pytestmark = pytest.mark.anyio


@pytest.fixture
async def products(client):
    async with SessionLocal() as db, db.begin():
        db.add_all([
            AccountProduct(type="CHECKING", name="입출금", description="d", interest_rate=0.1),
            AccountProduct(type="SAVINGS", name="적금", description="d", interest_rate=3.5),
            CardProduct(type="CREDIT", name="신용", description="d", credit_limit=3_000_000),
            CardProduct(type="DEBIT", name="체크", description="d"),
        ])


async def test_list_account_products(client, products):
    response = await client.get("/products/accounts")
    assert response.status_code == 200
    assert [p["name"] for p in response.json()["data"]] == ["입출금", "적금"]


async def test_list_account_products_filtered_by_type(client, products):
    response = await client.get("/products/accounts", params={"type": "SAVINGS"})
    assert [p["name"] for p in response.json()["data"]] == ["적금"]


async def test_list_account_products_invalid_type_is_422(client, products):
    response = await client.get("/products/accounts", params={"type": "LOAN"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_get_account_product(client, products):
    response = await client.get("/products/accounts/1")
    assert response.status_code == 200
    assert response.json()["data"]["interest_rate"] is not None
    assert response.json()["data"]["min_amount"] is None


async def test_get_account_product_not_found(client, products):
    response = await client.get("/products/accounts/999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACCOUNT_PRODUCT_NOT_FOUND"


async def test_list_card_products_shows_credit_limit_only_for_credit(client, products):
    response = await client.get("/products/cards")
    by_type = {p["type"]: p["credit_limit"] for p in response.json()["data"]}
    assert by_type == {"CREDIT": 3_000_000, "DEBIT": None}

    response = await client.get("/products/cards", params={"type": "DEBIT"})
    assert [p["name"] for p in response.json()["data"]] == ["체크"]


async def test_get_card_product_not_found(client, products):
    response = await client.get("/products/cards/999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CARD_PRODUCT_NOT_FOUND"


async def test_require_product_type_mismatch(client, products):
    async with SessionLocal() as db:
        assert (await product_service.require_account_product(db, 1, "CHECKING")).name == "입출금"
        with pytest.raises(BadRequestException) as exc:
            await product_service.require_account_product(db, 1, "SAVINGS")
        assert exc.value.code == "PRODUCT_TYPE_MISMATCH"

        with pytest.raises(BadRequestException):
            await product_service.require_card_product(db, 1, "DEBIT")  # 1번은 신용 상품
        with pytest.raises(NotFoundException):
            await product_service.require_card_product(db, 999, "CREDIT")
