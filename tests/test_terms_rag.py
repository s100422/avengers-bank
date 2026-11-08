"""약관 RAG: 청킹·색인·범위 검색·인용 (C-075). 외부 API 없이 가짜 임베딩·가짜 모델로 확인한다.

fixture: tests/fixtures/terms_rag/ (예금 상품 하나 + 신용카드 상품 하나, 둘 다 [early-close]·[fees] 조항이 있다.
r.marketing은 어떤 상품에도 연결되지 않은 공통 문서, r.product.deposit-a의 [notice]에는 프롬프트 주입 문장이 있다.)
"""

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.timezone import today_kst
from avengers_bank.domains.agent.model_client import ModelReply, get_model_client
from avengers_bank.domains.agent.service import extract_citations
from avengers_bank.domains.agent.tools import run_tool
from avengers_bank.domains.products.models import AccountProduct, CardProduct
from avengers_bank.domains.terms.chunking import MAX_CHARS, chunk_document
from avengers_bank.domains.terms.embedding import EmbeddingError, set_embedding_client
from avengers_bank.domains.terms.indexing import index_terms
from avengers_bank.domains.terms.loader import load_corpus
from avengers_bank.domains.terms.models import (
    TermsChunk,
    TermsConsent,
    TermsIndexEntry,
    TermsIndexGeneration,
    TermsVersion,
)
from avengers_bank.domains.terms.publish import publish_corpus
from avengers_bank.domains.users.schemas import UserResponse
from avengers_bank.main import app
from tests.test_agent import FakeClient, tool

pytestmark = pytest.mark.anyio

FIXTURE = Path(__file__).parent / "fixtures" / "terms_rag"
DEPOSIT = 4  # account_products 1~3 다음
CREDIT = 1  # card_products의 첫 상품 (계좌 상품 1번과 ID가 겹친다)
FUTURE = (today_kst() + timedelta(days=365)).isoformat()


class TopicEmbedder:
    """주제어 개수를 축으로 쓰는 결정적 임베딩. 주제어가 없는 글은 마지막 축(0.2)만 남아 유사도가 낮다."""

    TOPICS = ("중도해지", "수수료", "만기", "결제", "분실", "무시")

    def __init__(self, model_id="fake-topic", dimensions=7, broken=False):
        self.model_id, self.dimensions, self.broken = model_id, dimensions, broken
        self.calls = 0

    async def embed(self, texts, task):
        self.calls += 1
        if self.broken:
            raise EmbeddingError("테스트 실패")
        out = []
        for t in texts:
            v = [float(t.count(w)) for w in self.TOPICS] + [0.2]
            out.append(v)
        return out


@pytest.fixture
def embedder():
    e = TopicEmbedder()
    set_embedding_client(e)
    yield e
    set_embedding_client(None)


async def publish(root: Path = FIXTURE):
    async with SessionLocal() as db, db.begin():
        return await publish_corpus(db, load_corpus(root), date(2026, 11, 10))


async def index(e, **kw):
    return await index_terms(SessionLocal, e, model_id=e.model_id, dimensions=e.dimensions, **kw)


def bump_deposit_rules(tmp_path: Path) -> Path:
    """r.deposit.rules를 2.0.0(중도해지 배수 0.3)으로 올린 사본."""
    root = tmp_path / "terms_rag"
    shutil.copytree(FIXTURE, root)
    doc = root / "corpus" / "r.deposit.rules.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace('version: "1.0.0"', 'version: "2.0.0"')
                   .replace("0.5를 곱합니다", "0.3을 곱합니다"), encoding="utf-8")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["documents"] + [t for p in manifest["products"] for t in p["terms"]]:
        if item["document_key"] == "r.deposit.rules":
            item["version"] = "2.0.0"
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return root


@pytest.fixture
async def rag(client, make_user, account_products, embedder):
    async with SessionLocal() as db, db.begin():
        db.add(AccountProduct(type="DEPOSIT", name="RAG 테스트 예금", description="d", interest_rate=3))
        db.add(CardProduct(type="CREDIT", name="RAG 테스트 신용카드", description="d", credit_limit=1_000_000))
    await publish()
    headers = await make_user("ironman")
    other = await make_user("hulk")
    users = {}
    for who, h in (("tony", headers), ("bruce", other)):
        users[who] = UserResponse.model_validate((await client.get("/users/me", headers=h)).json()["data"])
    return {"tony": headers, "bruce": other, "users": users}


async def versions() -> dict[str, int]:
    async with SessionLocal() as db:
        return {f"{v.document_key}@{v.version}": v.terms_version_id for v in await db.scalars(select(TermsVersion))}


async def search(user, **args):
    outcome = await run_tool("search_product_terms", args, user)
    return json.loads(outcome.content)


# ── 청킹 ──────────────────────────────────────────────────────────────


def test_chunks_keep_tables_list_items_and_exceptions():
    long = "가" * 250
    table = "| 항목 | 값 |\n|---|---|\n" + "".join(f"| 행{i} | {i} |\n" for i in range(40))
    body = (f"# 문서\n\n## [big] 긴 조항\n\n{long}\n\n{long}\n\n{table}\n- 첫 항목\n  이어지는 줄\n- 둘째 항목\n\n{long}\n"
            "\n## [small] 짧은 조항\n\n본문.\n")
    chunks = chunk_document("문서", body)
    big = [c for c in chunks if c.section_id == "big"]
    assert len(big) > 1 and all(c.text.startswith("문서 > 긴 조항\n\n") for c in big)
    assert any(table.strip() in body[c.char_start:c.char_end] for c in big)  # 표는 한 청크 안에 통째로
    assert any("- 첫 항목\n  이어지는 줄" in c.text for c in big)
    assert all(c.char_end - c.char_start <= max(MAX_CHARS, len(table)) for c in big)
    assert [c.section_id for c in chunks if c.section_id != "big"] == ["preamble", "small"]

    doc = load_corpus(FIXTURE).documents[("r.deposit.rules", "1.0.0")]
    by_section = {c.section_id: c for c in chunk_document(doc.title, doc.body)}
    assert "0.5를 곱합니다" in by_section["early-close"].text and "단, 예외" in by_section["early-close"].text
    assert "| 해지 | 0원 |" in by_section["fees"].text
    assert by_section["fees"].text.startswith("RAG 예금 약관 > 수수료")


# ── 색인 ──────────────────────────────────────────────────────────────


async def test_index_is_idempotent_and_reindex_swaps_generation(rag, embedder):
    first = await index(embedder)
    assert first.activated and first.new_generation and not first.failed and len(first.indexed) == 5
    calls = embedder.calls
    again = await index(embedder)
    assert (again.generation_id, again.indexed, len(again.skipped)) == (first.generation_id, [], 5)
    assert embedder.calls == calls  # 바뀌지 않은 문서는 다시 임베딩하지 않는다

    re = await index(embedder, reindex=True)
    assert re.activated and re.generation_id != first.generation_id
    async with SessionLocal() as db:
        statuses = dict((await db.execute(select(TermsIndexGeneration.generation_id, TermsIndexGeneration.status))).all())
        per_gen = dict((await db.execute(
            select(TermsChunk.generation_id, func.count()).group_by(TermsChunk.generation_id))).all())
        dup = await db.scalar(select(func.count()).select_from(
            select(TermsChunk.generation_id, TermsChunk.terms_version_id, TermsChunk.ordinal)
            .group_by(TermsChunk.generation_id, TermsChunk.terms_version_id, TermsChunk.ordinal)
            .having(func.count() > 1).subquery()))
    assert statuses == {first.generation_id: "retired", re.generation_id: "active"}
    assert per_gen[first.generation_id] == per_gen[re.generation_id] == first.chunks and dup == 0


async def test_dry_run_writes_nothing(rag):
    report = await index_terms(SessionLocal, None, model_id="m", dimensions=7, dry_run=True)
    assert len(report.indexed) == 5 and report.chunks > 0 and report.generation_id is None
    async with SessionLocal() as db:
        assert await db.scalar(select(func.count()).select_from(TermsIndexGeneration)) == 0


async def test_failed_or_mismatched_index_is_not_ready_and_retried(rag, embedder):
    users = rag["users"]
    broken = TopicEmbedder(broken=True)
    report = await index(broken)
    assert len(report.failed) == 5 and not report.activated
    set_embedding_client(embedder)
    r = await search(users["tony"], query="중도해지", product_kind="deposit", product_id=DEPOSIT)
    assert r["error"]["code"] == "TERMS_INDEX_NOT_READY"

    # 차원이 설정과 다른 벡터 → 그 버전은 failed, 세대는 활성화되지 않는다
    wrong = TopicEmbedder()
    wrong.dimensions = 8  # 실제로는 7차원을 돌려준다
    report = await index_terms(SessionLocal, wrong, model_id="fake-topic", dimensions=8)
    assert len(report.failed) == 5 and not report.activated

    # 다음 실행에서 실패한 버전을 다시 처리한다 (부분 청크 없이)
    report = await index(embedder)
    assert report.activated and not report.failed and len(report.indexed) == 5
    async with SessionLocal() as db:
        statuses = set(await db.scalars(select(TermsIndexEntry.status).where(
            TermsIndexEntry.generation_id == report.generation_id)))
    assert statuses == {"ready"}

    # 검색 클라이언트의 모델·차원이 활성 세대와 다르면 검색하지 않는다
    set_embedding_client(TopicEmbedder(model_id="other-model"))
    r = await search(users["tony"], query="중도해지", product_kind="deposit", product_id=DEPOSIT)
    assert r["error"]["code"] == "TERMS_INDEX_NOT_READY"


# ── 범위 검색 ──────────────────────────────────────────────────────────


async def test_search_is_scoped_to_product_set(rag, embedder):
    await index(embedder)
    ids = await versions()
    tony = rag["users"]["tony"]
    dep = await search(tony, query="중도해지하면 어떻게 돼?", product_kind="deposit", product_id=DEPOSIT, top_k=5)
    assert dep["status"] == "ok" and dep["scope_label"] == "현재 가입 약관"
    top = dep["passages"][0]
    assert (top["document_key"], top["section_id"]) == ("r.deposit.rules", "early-close")
    assert top["url"] == f"/terms/{ids['r.deposit.rules@1.0.0']}#early-close"
    assert "단, 예외" in top["text"] and top["text"].startswith("<약관원문 ")
    allowed = {ids[k] for k in ("r.common@1.0.0", "r.deposit.rules@1.0.0", "r.product.deposit-a@1.0.0")}
    assert {p["terms_version_id"] for p in dep["passages"]} <= allowed  # 연결 안 된 마케팅·카드 약관 없음

    card = await search(tony, query="중도해지하면 어떻게 돼?", product_kind="credit", product_id=CREDIT, top_k=5)
    assert [(p["document_key"], p["section_id"]) for p in card["passages"]] == [("r.credit.rules", "early-close")]
    # 같은 숫자 ID라도 종류가 다르면 다른 상품: 계좌 상품 1번(CHECKING)에는 약관이 없다
    none = await search(tony, query="중도해지", product_kind="checking", product_id=1)
    assert none["status"] == "no_terms" and none["passages"] == []


async def test_insufficient_evidence_and_need_product(rag, embedder):
    await index(embedder)
    tony = rag["users"]["tony"]
    r = await search(tony, query="카드 분실 신고는 며칠 안에?", product_kind="credit", product_id=CREDIT)
    assert r["status"] == "insufficient_evidence" and r["passages"] == []

    r = await search(tony, query="중도해지 조건", product_kind="deposit")
    assert r["status"] == "need_product" and r["passages"] == []
    assert {(c["product_id"], c["name"]) for c in r["product_candidates"]} == {(2, "DEPOSIT"), (DEPOSIT, "RAG 테스트 예금")}


async def test_new_version_not_indexed_is_error_not_old_version(rag, embedder, tmp_path):
    await index(embedder)
    old = (await versions())["r.deposit.rules@1.0.0"]
    await publish(bump_deposit_rules(tmp_path))
    tony = rag["users"]["tony"]
    r = await search(tony, query="중도해지", product_kind="deposit", product_id=DEPOSIT)
    assert r["error"]["code"] == "TERMS_INDEX_NOT_READY"

    report = await index(embedder)
    assert report.indexed == ["r.deposit.rules@2.0.0"]
    r = await search(tony, query="중도해지", product_kind="deposit", product_id=DEPOSIT)
    top = r["passages"][0]
    assert top["version"] == "2.0.0" and "0.3을 곱합니다" in top["text"] and top["terms_version_id"] != old


async def test_my_contract_uses_consented_version(client, rag, embedder, tmp_path):
    tony, bruce = rag["tony"], rag["bruce"]
    r = await client.post("/accounts/deposit", json={"product_id": DEPOSIT, "maturity_date": FUTURE}, headers=tony)
    assert r.status_code == 201, r.text
    account_id = r.json()["data"]["account_id"]
    await publish(bump_deposit_rules(tmp_path))  # 가입 뒤에 약관이 v2로 바뀐다
    await index(embedder)

    users = rag["users"]
    mine = await search(users["tony"], query="중도해지", product_kind="deposit", scope="my_contract", subject_id=account_id)
    assert mine["status"] == "ok" and mine["scope_label"] == "가입 당시 동의 약관"
    assert mine["passages"][0]["version"] == "1.0.0" and "0.5를 곱합니다" in mine["passages"][0]["text"]
    now = await search(users["tony"], query="중도해지", product_kind="deposit", product_id=DEPOSIT)
    assert now["passages"][0]["version"] == "2.0.0"

    other = await search(users["bruce"], query="중도해지", product_kind="deposit", scope="my_contract", subject_id=account_id)
    assert other["error"]["code"] == "SUBJECT_NOT_FOUND"
    missing = await run_tool("search_product_terms", {"query": "q", "product_kind": "deposit", "scope": "my_contract"}, users["tony"])
    assert json.loads(missing.content)["error"]["code"] == "INVALID_ARGUMENTS"

    async with SessionLocal() as db, db.begin():  # 동의 기록 도입 전 가입과 같은 상태
        await db.execute(delete(TermsConsent))
    r = await search(users["tony"], query="중도해지", product_kind="deposit", scope="my_contract", subject_id=account_id)
    assert r["status"] == "no_consent_record" and r["passages"] == []
    assert bruce  # 다른 사용자도 실제로 있다


# ── 채팅·인용 ─────────────────────────────────────────────────────────


@pytest.fixture
def fake():
    holder = {}

    def use(*steps):
        holder["client"] = FakeClient(*steps)
        app.dependency_overrides[get_model_client] = lambda: holder["client"]
        return holder["client"]

    yield use
    app.dependency_overrides.pop(get_model_client, None)


def _result(turns, index=-1):
    return json.loads(turns[index].results[0].content)


async def test_chat_citations_only_from_this_request(client, rag, embedder, fake):
    await index(embedder)
    seen = {}

    def answer(turns):
        data = _result(turns)
        # 주입 문장이 있는 조항도 검색 결과로 그냥 돌아온다 (도구 동작은 바뀌지 않는다)
        seen["ids"] = [p["source_id"] for p in data["passages"]]
        seen["texts"] = [p["text"] for p in data["passages"]]
        fees = next(p["source_id"] for p in data["passages"] if p["section_id"] == "fees")
        return tool("get_terms_section", source_id=fees)

    def final(turns):
        section = _result(turns)
        seen["section"] = section["passage"]["text"]
        fees = section["passage"]["source_id"]
        return ModelReply(f"증명서 발급 수수료는 1,000원입니다 [[src:{fees}]]. 모두 0원 [[src:999:fake]] [[src:1:nope]]")

    fake(tool("search_product_terms", query="수수료 알려줘", product_kind="deposit", product_id=DEPOSIT, top_k=5),
         answer, final)
    r = await client.post("/agent/chat", json={"message": "수수료?"}, headers=rag["tony"])
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert any("이전 지시를 모두 무시" in t for t in seen["texts"])
    assert "| 증명서 발급 | 1,000원 |" in seen["section"]
    assert body["answer"] == "증명서 발급 수수료는 1,000원입니다. 모두 0원"  # 표시는 모두 지운다
    ids = await versions()
    (citation,) = body["citations"]  # 지어낸 id·검색만 되고 인용 안 된 출처는 없다
    assert citation == {
        "source_id": f"{ids['r.deposit.rules@1.0.0']}:fees", "document_version_id": ids["r.deposit.rules@1.0.0"],
        "title": "RAG 예금 약관", "version": "1.0.0", "section_id": "fees", "section_title": "수수료",
        "url": f"/terms/{ids['r.deposit.rules@1.0.0']}#fees",
    }
    assert body["action"] is None

    cid = body["conversation_id"]
    messages = (await client.get(f"/agent/conversations/{cid}/messages", headers=rag["tony"])).json()["data"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["citations"] == [citation] and messages[0]["citations"] == []
    assert (await client.get(f"/agent/conversations/{cid}/messages", headers=rag["bruce"])).status_code == 404
    assert (await client.get(f"/agent/conversations/{cid}/messages")).status_code == 401


async def test_section_only_for_sources_searched_in_same_request(client, rag, embedder, fake):
    await index(embedder)
    ids = await versions()
    guessed = f"{ids['r.deposit.rules@1.0.0']}:early-close"  # 형식이 맞는 id라도 이번 요청에서 검색하지 않았으면 거절
    f = fake(tool("get_terms_section", source_id=guessed), ModelReply(f"답 [[src:{guessed}]]"))
    body = (await client.post("/agent/chat", json={"message": "q"}, headers=rag["tony"])).json()["data"]
    data, is_error = f.tool_result(1)
    assert is_error and data["error"]["code"] == "SOURCE_NOT_FOUND"
    assert body["citations"] == [] and body["answer"] == "답"
    # 채팅 밖(요청 목록 없음)에서도 거절
    out = await run_tool("get_terms_section", {"source_id": guessed}, rag["users"]["tony"])
    assert not out.ok


def test_extract_citations_drops_unknown_and_dedupes():
    text, cites = extract_citations("가 [[src:a]] 나 [[src:a]] 다 [[src:x]]", {})
    assert (text, cites) == ("가 나 다", [])


def test_named_product_resolves_only_unambiguous_names():
    from avengers_bank.domains.agent.tools.terms import ProductCandidate, named_product

    c = [ProductCandidate(product_id=i, name=n) for i, n in
         [(2, "어벤져스 정기예금"), (5, "어벤져스 스타 정기예금"), (8, "어벤져스 청년 도약 적금")]]
    assert named_product(c, "어벤져스 정기예금 중도해지하면?").product_id == 2
    assert named_product(c, "스타 정기예금 만기").product_id == 5  # 더 긴 이름이 이긴다
    assert named_product(c, "청년도약적금 나이 제한").product_id == 8  # 띄어쓰기 무시, 두 단어 이상 줄임말
    assert named_product(c, "정기예금 중도해지 알려줘") is None  # 종류 이름만으로는 고르지 않는다
    assert named_product(c, "어벤져스 정기예금이랑 스타 정기예금 비교") is None  # 둘 다 → 모호
