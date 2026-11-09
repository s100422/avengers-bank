"""이체 화면의 최근·자주 쓰는 계좌, 우리 은행 수취 조회."""
import pytest
from sqlalchemy import select

from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.interbank.models import InterbankTransfer
from avengers_bank.domains.transfers.contacts import mask_name
from avengers_bank.domains.users.models import User

pytestmark = pytest.mark.anyio


@pytest.fixture
async def world(client, make_user, account_products):
    """토니(입출금 1번, 100만 원)와 브루스(입출금 2번)."""
    tony, bruce = await make_user("ironman"), await make_user("hulk")
    a = (await client.post("/accounts/checking", json={"product_id": 1}, headers=tony)).json()["data"]
    b = (await client.post("/accounts/checking", json={"product_id": 1}, headers=bruce)).json()["data"]
    await client.post("/dev/accounts/checking/1/charge", json={"amount": 1_000_000}, headers=tony)
    return {"tony": tony, "bruce": bruce, "a": a, "b": b}


async def name_of(login_id):
    async with SessionLocal() as db:
        return await db.scalar(select(User.name).where(User.login_id == login_id))


def test_mask_name():
    assert [mask_name(n) for n in ["홍", "홍길", "홍길동", "남궁민수"]] == ["홍", "홍*", "홍*동", "남**수"]


async def test_inquiry_masks_holder_name(client, world):
    res = await client.post("/transfers/inquiry", json={"to_account_num": world["b"]["account_num"]}, headers=world["tony"])
    assert res.status_code == 200
    name = await name_of("hulk")
    assert res.json()["data"]["holder_name"] == mask_name(name) and name not in res.json()["data"]["holder_name"]
    res = await client.post("/transfers/inquiry", json={"to_account_num": "000-000-000000"}, headers=world["tony"])
    assert res.status_code == 404 and res.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"
    assert (await client.post("/transfers/inquiry", json={"to_account_num": "x"})).status_code == 401


async def test_favorites_add_is_idempotent_list_and_remove(client, world):
    body = {"bank_code": "", "bank_name": "SpiderBank", "account": world["b"]["account_num"], "name": "브루스"}
    first = await client.post("/transfers/favorites", json=body, headers=world["tony"])
    again = await client.post("/transfers/favorites", json=body, headers=world["tony"])
    assert first.status_code == 201 and again.json()["data"]["favorite_id"] == first.json()["data"]["favorite_id"]
    other_bank = {**body, "bank_code": "902", "bank_name": "SimBank"}  # 같은 번호라도 은행이 다르면 다른 계좌
    await client.post("/transfers/favorites", json=other_bank, headers=world["tony"])
    listed = (await client.get("/transfers/favorites", headers=world["tony"])).json()["data"]
    assert [f["bank_code"] for f in listed] == ["902", ""]  # 최근에 추가한 것이 위
    assert (await client.get("/transfers/favorites", headers=world["bruce"])).json()["data"] == []  # 남의 목록은 안 보인다

    fid = first.json()["data"]["favorite_id"]
    assert (await client.delete(f"/transfers/favorites/{fid}", headers=world["bruce"])).status_code == 404  # 남의 것
    assert (await client.delete(f"/transfers/favorites/{fid}", headers=world["tony"])).status_code == 200
    assert (await client.delete(f"/transfers/favorites/{fid}", headers=world["tony"])).status_code == 404
    assert len((await client.get("/transfers/favorites", headers=world["tony"])).json()["data"]) == 1


async def test_favorite_validation(client, world):
    for bad in ({"bank_code": "12", "bank_name": "x", "account": "1"}, {"bank_code": "", "bank_name": "x", "account": ""}):
        assert (await client.post("/transfers/favorites", json=bad, headers=world["tony"])).status_code == 422


async def test_recent_lists_transfer_targets_with_favorite_state(client, world):
    tony = world["tony"]
    assert (await client.get("/transfers/recent", headers=tony)).json()["data"] == []
    sent = await client.post("/transfers", headers=tony, json={
        "from_checking_account_id": 1, "to_account_num": world["b"]["account_num"], "amount": 1000, "account_password": "1357"})
    assert sent.status_code == 201
    recent = (await client.get("/transfers/recent", headers=tony)).json()["data"]
    assert len(recent) == 1 and recent[0]["account"] == world["b"]["account_num"]
    assert recent[0]["bank_code"] == "" and recent[0]["name"] == await name_of("hulk") and recent[0]["favorite_id"] is None

    star = await client.post("/transfers/favorites", headers=tony, json={
        "bank_code": "", "bank_name": recent[0]["bank_name"], "account": recent[0]["account"], "name": recent[0]["name"]})
    again = (await client.get("/transfers/recent", headers=tony)).json()["data"]
    assert len(again) == 1 and again[0]["favorite_id"] == star.json()["data"]["favorite_id"]  # 최근 목록에도 남고 별만 채워진다
    await client.delete(f"/transfers/favorites/{again[0]['favorite_id']}", headers=tony)
    assert (await client.get("/transfers/recent", headers=tony)).json()["data"][0]["favorite_id"] is None

    assert (await client.get("/transfers/recent", headers=world["bruce"])).json()["data"] == []  # 받은 사람에게는 안 보인다


async def test_recent_includes_other_bank_skips_failed_and_own_accounts(client, world):
    async with SessionLocal() as db, db.begin():
        for tid, bank, acct, name, status in [
            ("00000000-0000-4000-8000-000000000001", "902", "110-123-0001", "김철수", "COMPLETED"),
            ("00000000-0000-4000-8000-000000000002", "902", "110-123-0002", None, "FAILED"),
            ("00000000-0000-4000-8000-000000000003", "902", "110-123-0003", None, "PENDING"),
        ]:
            db.add(InterbankTransfer(transfer_id=tid, direction="OUT", checking_account_id=1, peer_bank=bank,
                                     peer_bank_name="SimBank", peer_account=acct, peer_name=name, amount=1000, memo="", status=status))
    recent = (await client.get("/transfers/recent", headers=world["tony"])).json()["data"]
    assert {r["account"] for r in recent} == {"110-123-0001", "110-123-0003"}  # 실패한 이체는 뺀다
    first = next(r for r in recent if r["account"] == "110-123-0001")
    assert first["bank_code"] == "902" and first["bank_name"] == "SimBank" and first["name"] == "김철수"
    # 내 계좌끼리 보낸 이체는 최근에 나오지 않는다 ('내 계좌' 탭이 따로 있다)
    mine = await client.post("/accounts/checking", json={"product_id": 1}, headers=world["tony"])
    await client.post("/transfers", headers=world["tony"], json={
        "from_checking_account_id": 1, "to_account_num": mine.json()["data"]["account_num"], "amount": 1000, "account_password": "1357"})
    recent = (await client.get("/transfers/recent", headers=world["tony"])).json()["data"]
    assert mine.json()["data"]["account_num"] not in {r["account"] for r in recent}
