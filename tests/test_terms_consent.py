"""약관 발행·가입 동의·가입 당시 약관 (C-075). fixture: tests/fixtures/terms/"""

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.timezone import today_kst
from avengers_bank.domains.accounts.models import CheckingAccount, DepositAccount
from avengers_bank.domains.products.models import AccountProduct, CardProduct
from avengers_bank.domains.terms import service as terms_service
from avengers_bank.domains.terms.loader import TermsSourceError, load_corpus
from avengers_bank.domains.terms.models import ProductTermsRevision, TermsConsent, TermsVersion
from avengers_bank.domains.terms.publish import publish_corpus

pytestmark = pytest.mark.anyio

FIXTURE = Path(__file__).parent / "fixtures" / "terms"
EFFECTIVE = date(2026, 11, 10)
FUTURE = (today_kst() + timedelta(days=365)).isoformat()


async def publish(root: Path = FIXTURE):
    async with SessionLocal() as db, db.begin():
        return await publish_corpus(db, load_corpus(root), EFFECTIVE)


def bump(tmp_path: Path, key: str, new_body_line: str) -> Path:
    """fixture를 복사해 문서 하나를 2.0.0으로 올린다 (새 버전 발행 시나리오)."""
    root = tmp_path / "terms"
    shutil.copytree(FIXTURE, root)
    doc = root / "corpus" / f"{key}.md"
    doc.write_text(
        doc.read_text(encoding="utf-8").replace('"version": "1.0.0"', '"version": "2.0.0"') + new_body_line + "\n",
        encoding="utf-8",
    )
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for d in manifest["documents"]:
        if d["document_key"] == key:
            d["version"] = "2.0.0"
    for p in manifest["products"]:
        for t in p["terms"]:
            if t["document_key"] == key:
                t["version"] = "2.0.0"
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return root


@pytest.fixture
async def products(client, account_products):
    """계좌 상품 1~3(CHECKING/DEPOSIT/SAVINGS) + 카드 상품 1(신용)·2(체크)를 만들고 fixture 약관을 발행한다."""
    async with SessionLocal() as db, db.begin():
        db.add_all([
            CardProduct(type="CREDIT", name="신용", description="d", credit_limit=1_000_000),
            CardProduct(type="DEBIT", name="체크", description="d"),
        ])
    await publish()
    client.auto_terms = False


async def terms_of(client, kind, product_id):
    return (await client.get(f"/terms/products/{kind}/{product_id}")).json()["data"]


def consent(data, agree=True, **override):
    body = {
        "revision_id": data["revision_id"], "set_hash": data["set_hash"],
        "agreements": [{"terms_version_id": i["terms_version_id"], "agreed": agree or not i["required"]}
                       for i in data["items"]],
    }
    return {**body, **override}


async def open_checking(client, headers, product_id=1):
    return await client.post("/accounts/checking", json={"product_id": product_id}, headers=headers)


def bodies(checking_id):
    """종류별 (경로, 상품 ID, 가입 본문)."""
    return {
        "checking": ("/accounts/checking", 1, {"product_id": 1}),
        "deposit": ("/accounts/deposit", 2, {"product_id": 2, "maturity_date": FUTURE, "initial_amount": 1000,
                                              "from_checking_account_id": checking_id}),
        "savings": ("/accounts/savings", 3, {"product_id": 3, "maturity_date": FUTURE,
                                              "monthly_payment": 10_000, "monthly_deposit_date": 5}),
        "credit": ("/cards/credit", 1, {"product_id": 1, "checking_account_id": checking_id, "payment_date": 14}),
        "debit": ("/cards/debit", 2, {"product_id": 2, "checking_account_id": checking_id}),
    }


async def count(model) -> int:
    async with SessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(model))


async def make_checking(client, headers) -> int:
    data = await terms_of(client, "checking", 1)
    r = await client.post("/accounts/checking", json={"product_id": 1, "terms": consent(data)}, headers=headers)
    assert r.status_code == 201, r.text
    account_id = r.json()["data"]["account_id"]
    await client.post(f"/dev/accounts/checking/{account_id}/charge", json={"amount": 10_000}, headers=headers)  # 예금 가입용
    return account_id


# ── 발행 ──────────────────────────────────────────────────────────────


async def test_publish_maps_products_and_is_idempotent(products, client):
    data = await terms_of(client, "checking", 1)
    assert [(i["document_key"], i["required"]) for i in data["items"]] == [
        ("t.common", True), ("t.account", True), ("t.optional", False)
    ]
    assert data["product_code"] == "fx-checking"
    # 계좌·카드 상품 ID가 겹쳐도 종류별로 다른 집합
    assert [i["document_key"] for i in (await terms_of(client, "credit", 1))["items"]] == ["t.common", "t.card"]

    again = await publish()
    assert again.inserted == [] and again.revisions == [] and again.mapped == []
    assert await count(TermsVersion) == 4 and await count(ProductTermsRevision) == 5


async def test_publish_refuses_to_overwrite_same_version(products, tmp_path):
    root = bump(tmp_path, "t.account", "바뀐 문장")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for d in manifest["documents"]:  # 내용은 바꾸고 버전은 그대로 1.0.0
        d["version"] = "1.0.0"
    for p in manifest["products"]:
        for t in p["terms"]:
            t["version"] = "1.0.0"
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    doc = root / "corpus" / "t.account.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace('"version": "2.0.0"', '"version": "1.0.0"'), encoding="utf-8")

    with pytest.raises(TermsSourceError, match="version을 올려"):
        await publish(root)


async def test_publish_requires_exactly_one_seed_match(client, account_products):
    async with SessionLocal() as db, db.begin():
        db.add(AccountProduct(type="CHECKING", name="CHECKING", description="d", interest_rate=1))  # 이름 중복
    with pytest.raises(TermsSourceError) as e:
        await publish()
    joined = "\n".join(e.value.errors)
    assert "fx-checking" in joined and "2개" in joined  # 2개 매칭
    assert "fx-credit" in joined and "0개" in joined  # 카드 상품이 없음
    assert await count(TermsVersion) == 0  # 호출한 쪽 트랜잭션이 롤백됨


async def test_loader_rejects_bad_sources(tmp_path):
    root = tmp_path / "terms"
    shutil.copytree(FIXTURE, root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["documents"][0]["path"] = "../README.md"  # corpus 밖
    manifest["products"][0]["terms"].append({"document_key": "t.card", "version": "1.0.0", "required": True, "order": 9})
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (root / "corpus" / "stray.md").write_text("---\n{}\n---\n", encoding="utf-8")
    with pytest.raises(TermsSourceError) as e:
        load_corpus(root)
    joined = "\n".join(e.value.errors)
    assert "corpus/ 아래" in joined  # 경로 이탈
    assert "product_kinds에 checking가 없습니다" in joined  # 종류 불일치
    assert "manifest에 없는 corpus 문서" in joined


async def test_real_corpus_is_valid():
    corpus = load_corpus(Path(__file__).parents[1] / "docs" / "terms")
    assert len(corpus.products) == 15


# ── 가입 동의 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", ["checking", "deposit", "savings", "credit", "debit"])
async def test_every_signup_path_requires_consent(products, client, make_user, kind):
    headers = await make_user()
    checking_id = await make_checking(client, headers)
    path, product_id, body = bodies(checking_id)[kind]
    data = await terms_of(client, kind, product_id)
    before = await count(TermsConsent)

    r = await client.post(path, json=body, headers=headers)  # terms 없음
    assert r.status_code == 422

    r = await client.post(path, json={**body, "terms": consent(data, agree=False)}, headers=headers)
    assert (r.status_code, r.json()["error"]["code"]) == (400, "TERMS_REQUIRED_NOT_AGREED")

    r = await client.post(path, json={**body, "terms": {**consent(data), "revision_id": data["revision_id"] + 99}},
                          headers=headers)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "TERMS_OUTDATED")
    assert await count(TermsConsent) == before  # 실패한 요청은 아무것도 남기지 않는다

    r = await client.post(path, json={**body, "terms": consent(data)}, headers=headers)
    assert r.status_code == 201, r.text
    subject_id = r.json()["data"]["account_id" if kind in ("checking", "deposit", "savings") else "card_id"]
    record = (await client.get(f"/terms/consents/{kind}/{subject_id}", headers=headers)).json()["data"]
    assert record["has_record"] is True
    assert [i["terms_version_id"] for i in record["items"]] == [i["terms_version_id"] for i in data["items"]]


@pytest.mark.parametrize("mutate", [
    lambda a: a + [{"terms_version_id": a[0]["terms_version_id"], "agreed": True}],  # 중복
    lambda a: a[:-1],  # 누락
    lambda a: a + [{"terms_version_id": 9999, "agreed": True}],  # 없는 버전
    lambda a: [{**x, "terms_version_id": x["terms_version_id"] + 100} for x in a],  # 다른 버전
])
async def test_manipulated_agreements_are_rejected(products, client, make_user, mutate):
    headers = await make_user()
    data = await terms_of(client, "checking", 1)
    terms = consent(data)
    terms["agreements"] = mutate(terms["agreements"])
    r = await client.post("/accounts/checking", json={"product_id": 1, "terms": terms}, headers=headers)
    assert (r.status_code, r.json()["error"]["code"]) == (400, "TERMS_INVALID")
    assert await count(CheckingAccount) == 0


async def test_terms_of_another_product_are_rejected(products, client, make_user):
    headers = await make_user()
    deposit_terms = consent(await terms_of(client, "deposit", 2))
    r = await client.post("/accounts/checking", json={"product_id": 1, "terms": deposit_terms}, headers=headers)
    assert r.json()["error"]["code"] == "TERMS_OUTDATED"  # 다른 상품의 revision


async def test_string_true_is_not_consent(products, client, make_user):
    headers = await make_user()
    terms = consent(await terms_of(client, "checking", 1))
    terms["agreements"][0]["agreed"] = "true"
    r = await client.post("/accounts/checking", json={"product_id": 1, "terms": terms}, headers=headers)
    assert r.status_code == 422


async def test_optional_terms_can_be_declined(products, client, make_user):
    headers = await make_user()
    data = await terms_of(client, "checking", 1)
    terms = consent(data)
    terms["agreements"][-1]["agreed"] = False  # t.optional
    r = await client.post("/accounts/checking", json={"product_id": 1, "terms": terms}, headers=headers)
    assert r.status_code == 201
    record = (await client.get(f"/terms/consents/checking/{r.json()['data']['account_id']}", headers=headers)).json()
    assert [(i["document_key"], i["agreed"]) for i in record["data"]["items"]] == [
        ("t.common", True), ("t.account", True), ("t.optional", False)
    ]


async def test_product_without_terms_cannot_be_opened(client, account_products, make_user):
    client.auto_terms = False
    headers = await make_user()
    r = await client.get("/terms/products/checking/1")
    assert (r.status_code, r.json()["error"]["code"]) == (409, "TERMS_NOT_CONFIGURED")
    fake = {"revision_id": 1, "set_hash": "x", "agreements": [{"terms_version_id": 1, "agreed": True}]}
    r = await client.post("/accounts/checking", json={"product_id": 1, "terms": fake}, headers=headers)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "TERMS_NOT_CONFIGURED")


async def test_card_issue_failure_rolls_back_consent(products, client, make_user):
    owner = await make_user("owner")
    other = await make_user("other")
    others_checking = await make_checking(client, other)
    before = await count(TermsConsent)
    data = await terms_of(client, "debit", 2)
    r = await client.post(
        "/cards/debit", json={"product_id": 2, "checking_account_id": others_checking, "terms": consent(data)},
        headers=owner,
    )
    assert r.status_code == 404  # 남의 계좌로는 발급 불가
    assert await count(TermsConsent) == before


async def test_consent_failure_rolls_back_account(products, client, make_user, monkeypatch):
    headers = await make_user()

    async def broken(*args, **kwargs):
        raise RuntimeError("동의 기록 실패")

    monkeypatch.setattr(terms_service, "record_consent", broken)
    data = await terms_of(client, "checking", 1)
    with pytest.raises(RuntimeError):
        await client.post("/accounts/checking", json={"product_id": 1, "terms": consent(data)}, headers=headers)
    assert await count(CheckingAccount) == 0


# ── 버전 변경 ────────────────────────────────────────────────────────────


async def test_stale_screen_requires_reconsent_and_old_consent_is_preserved(products, client, make_user, tmp_path):
    headers = await make_user()
    checking_id = await make_checking(client, headers)
    v1 = await terms_of(client, "deposit", 2)
    body = {"product_id": 2, "maturity_date": FUTURE, "initial_amount": 1000, "from_checking_account_id": checking_id}
    r = await client.post("/accounts/deposit", json={**body, "terms": consent(v1)}, headers=headers)
    old_account = r.json()["data"]["account_id"]
    old_version_id = v1["items"][1]["terms_version_id"]
    old_text = (await client.get(f"/terms/versions/{old_version_id}")).json()["data"]["body"]

    stale = await terms_of(client, "deposit", 2)  # 화면을 열어 둔 상태
    report = await publish(bump(tmp_path, "t.account", "중도해지 규정이 바뀌었습니다."))
    assert report.inserted == ["t.account@2.0.0"]
    assert "t.account@1.0.0" in report.retired

    r = await client.post("/accounts/deposit", json={**body, "terms": consent(stale)}, headers=headers)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "TERMS_OUTDATED")

    fresh = await terms_of(client, "deposit", 2)
    assert fresh["revision_id"] != stale["revision_id"]
    r = await client.post("/accounts/deposit", json={**body, "terms": consent(fresh)}, headers=headers)
    assert r.status_code == 201

    # 예전 가입은 예전 버전 그대로, 원문도 바뀌지 않는다
    record = (await client.get(f"/terms/consents/deposit/{old_account}", headers=headers)).json()["data"]
    assert [i["version"] for i in record["items"]] == ["1.0.0", "1.0.0"]
    old = (await client.get(f"/terms/versions/{old_version_id}")).json()["data"]
    assert old["body"] == old_text and old["status"] == "retired"
    assert [s["section_id"] for s in old["sections"]] == ["preamble", "limits", "early-close"]


# ── 가입 당시 약관 조회 ──────────────────────────────────────────────────


async def test_other_users_consent_record_is_hidden(products, client, make_user):
    owner = await make_user("owner")
    other = await make_user("other")
    account_id = await make_checking(client, owner)
    r = await client.get(f"/terms/consents/checking/{account_id}", headers=other)
    assert r.status_code == 404
    assert (await client.get(f"/terms/consents/checking/{account_id}")).status_code == 401


async def test_legacy_account_has_no_fabricated_record(products, client, make_user):
    headers = await make_user()
    async with SessionLocal() as db, db.begin():  # 약관 기능 도입 전에 개설된 계좌
        db.add(DepositAccount(user_id=1, product_id=2, account_num="120-000-000001", maturity_date=date(2030, 1, 1)))
    r = await client.get("/terms/consents/deposit/1", headers=headers)
    assert r.json()["data"] == {
        "subject_kind": "deposit", "subject_id": 1, "has_record": False, "recorded_at": None, "items": []
    }
    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(TermsConsent)) == 0


async def test_terms_endpoints_work_without_ai(products, client, monkeypatch):
    """AI·임베딩 키가 없어도 원문 열람·약관 목록은 된다."""
    from avengers_bank.core.config import get_settings

    monkeypatch.setattr(get_settings(), "gemini_api_key", None)
    data = await terms_of(client, "checking", 1)
    r = await client.get(f"/terms/versions/{data['items'][0]['terms_version_id']}")
    assert r.status_code == 200 and "적용 범위" in r.json()["data"]["body"]
