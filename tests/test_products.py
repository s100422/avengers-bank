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


# ── 찜한 상품 (C-117) ─────────────────────────────────────────────────────


async def test_favorite_products_add_list_remove(client, products, make_user):
    tony, bruce = await make_user("ironman"), await make_user("hulk")
    assert (await client.get("/products/favorites")).status_code == 401
    # 계좌 상품 1번(입출금)과 카드 상품 1번(신용)은 id가 같아도 다른 찜이다
    for path in ["CHECKING/1", "CREDIT/1", "SAVINGS/2", "SAVINGS/2"]:  # 두 번 찜해도 한 건
        assert (await client.put(f"/products/favorites/{path}", headers=tony)).status_code == 200
    listed = (await client.get("/products/favorites", headers=tony)).json()["data"]
    assert [(f["product_type"], f["product_id"]) for f in listed] == [("SAVINGS", 2), ("CREDIT", 1), ("CHECKING", 1)]
    assert listed[0]["name"] == "적금" and listed[0]["interest_rate"] == "3.50" and listed[0]["credit_limit"] is None
    assert listed[1]["credit_limit"] == 3_000_000 and listed[1]["interest_rate"] is None
    assert (await client.get("/products/favorites", headers=bruce)).json()["data"] == []  # 남의 찜은 안 보인다

    assert (await client.delete("/products/favorites/CREDIT/1", headers=bruce)).status_code == 200  # 남의 것은 지워지지 않는다
    assert len((await client.get("/products/favorites", headers=tony)).json()["data"]) == 3
    for _ in range(2):  # 이미 해제된 것도 성공
        assert (await client.delete("/products/favorites/CREDIT/1", headers=tony)).status_code == 200
    listed = (await client.get("/products/favorites", headers=tony)).json()["data"]
    assert [(f["product_type"], f["product_id"]) for f in listed] == [("SAVINGS", 2), ("CHECKING", 1)]


async def test_favorite_products_validation(client, products, make_user):
    tony = await make_user("ironman")
    res = await client.put("/products/favorites/CHECKING/99", headers=tony)
    assert res.status_code == 404 and res.json()["error"]["code"] == "ACCOUNT_PRODUCT_NOT_FOUND"
    res = await client.put("/products/favorites/DEPOSIT/1", headers=tony)  # 1번은 입출금 상품
    assert res.status_code == 400 and res.json()["error"]["code"] == "PRODUCT_TYPE_MISMATCH"
    assert (await client.put("/products/favorites/LOAN/1", headers=tony)).status_code == 422
    assert (await client.get("/products/favorites", headers=tony)).json()["data"] == []
