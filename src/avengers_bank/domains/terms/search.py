"""약관 검색 (C-075). 서버가 먼저 범위(상품·버전)를 정하고, 그 버전의 청크 안에서만 순위를 매긴다.

- current: 상품의 현재 적용 집합 / my_contract: 사용자가 가입할 때 동의한 버전 (남의 계좌·카드면 404).
- 범위의 버전이 활성 색인 세대에서 하나라도 ready가 아니면 오류. 옛 버전으로 대신 답하지 않는다.
- 순위: 벡터 유사도(코사인, PostgreSQL은 pgvector <=>, SQLite 테스트는 파이썬) + 가벼운 키워드 점수.
  근거 여부는 벡터 유사도가 terms_min_score 이상인지로만 판단한다. 점수는 정답 확률이 아니다.
- 질의 임베딩을 기다리기 전에 DB 커넥션을 돌려준다 (commit하면 세션이 커넥션을 반납한다).
"""

import math
import re
from dataclasses import dataclass, field

from sqlalchemy import Float, cast, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.exceptions import ApiException
from avengers_bank.domains.terms import service as terms_service
from avengers_bank.domains.terms.embedding import EmbeddingClient, EmbeddingError
from avengers_bank.domains.terms.indexing import active_generation
from avengers_bank.domains.terms.markdown import parse_sections
from avengers_bank.domains.terms.models import TermsChunk, TermsIndexEntry, TermsVersion, Vector
from avengers_bank.domains.users.schemas import UserResponse

SCOPE_LABELS = {"current": "현재 가입 약관", "my_contract": "가입 당시 동의 약관"}
KEYWORD_WEIGHT = 0.15  # 퓨전: vector + 0.15 × keyword. 키워드는 같은 근거 후보끼리 순서를 다듬는 정도로만 쓴다
CANDIDATES = 50  # PostgreSQL에서 벡터로 먼저 고르는 후보 수 (범위가 상품 하나라 보통 이보다 적다)
SECTION_CONTEXT_CHARS = 2400  # 나뉜 조항은 이 길이까지 조항 전체를, 넘으면 맞은 청크 주변만 돌려준다
NEIGHBOR_CHARS = 400

NOT_READY = ApiException(503, "TERMS_INDEX_NOT_READY", "약관 검색 색인이 아직 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.")


# ── 순위 (평가 스크립트와 같이 쓰는 순수 함수) ─────────────────────────────


def _bigrams(text: str) -> set[str]:
    s = re.sub(r"[^0-9a-z가-힣]", "", text.lower())
    return {s[i:i + 2] for i in range(len(s) - 1)}


def keyword_score(query: str, text: str, section_id: str = "", section_title: str = "") -> float:
    """0~1. 질의 글자 2-gram 중 본문에 있는 비율. 질의에 조항 ID·제목이 그대로 있으면 1."""
    q = query.lower()
    if (section_id and section_id in q) or (len(section_title) >= 2 and section_title.lower() in q):
        return 1.0
    grams = _bigrams(query)
    return len(grams & _bigrams(text)) / len(grams) if grams else 0.0


def fuse(vector_score: float, keyword: float) -> float:
    return vector_score + KEYWORD_WEIGHT * keyword


@dataclass
class Candidate:
    key: tuple  # 중복 제거 단위: (버전, 조항)
    vector_score: float
    text: str
    section_id: str
    section_title: str
    payload: object = None
    score: float = field(default=0.0)


def rank(query: str, candidates: list[Candidate], top_k: int, min_score: float) -> list[Candidate]:
    """벡터 유사도가 min_score 미만인 후보는 버리고, 퓨전 점수로 정렬한 뒤 조항 단위로 중복을 없앤다.
    빈 목록 = 근거 부족 (상위 결과라고 관련 있다고 보지 않는다)."""
    kept = []
    for c in candidates:
        if c.vector_score >= min_score:
            c.score = fuse(c.vector_score, keyword_score(query, c.text, c.section_id, c.section_title))
            kept.append(c)
    out, seen = [], set()
    for c in sorted(kept, key=lambda c: c.score, reverse=True):
        if c.key not in seen:
            seen.add(c.key)
            out.append(c)
    return out[:top_k]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / ((math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))) or 1.0)


# ── 범위 결정과 검색 ─────────────────────────────────────────────────────


@dataclass
class Passage:
    source_id: str
    terms_version_id: int
    document_key: str
    title: str
    version: str
    section_id: str
    section_title: str
    text: str
    url: str


@dataclass
class SearchOutcome:
    status: str  # ok / insufficient_evidence / no_terms / no_consent_record
    scope_label: str
    passages: list[Passage] = field(default_factory=list)


def source_id(terms_version_id: int, section_id: str) -> str:
    return f"{terms_version_id}:{section_id}"


def section_text(body: str, section_id: str) -> tuple[str, str] | None:
    for s in parse_sections(body):
        if s.section_id == section_id:
            return s.title, body[s.start:s.end].strip()
    return None


def _context(body: str, section_id: str, start: int, end: int) -> str:
    """조항 전체(짧으면) 또는 맞은 청크와 앞뒤 이웃 글."""
    for s in parse_sections(body):
        if s.section_id == section_id:
            if s.end - s.start <= SECTION_CONTEXT_CHARS:
                return body[s.start:s.end].strip()
            return body[max(s.start, start - NEIGHBOR_CHARS):min(s.end, end + NEIGHBOR_CHARS)].strip()
    return body[start:end]


async def scoped_versions(
    db: AsyncSession, user: UserResponse, scope: str, kind: str, product_id: int | None, subject_id: int | None
) -> list[TermsVersion] | None:
    if scope == "my_contract":
        return await terms_service.get_consented_versions(db, user, kind, subject_id)
    current = await terms_service.get_current_set(db, kind, product_id)
    return None if current is None else [i.version for i in current.items]


async def search_terms(
    db: AsyncSession, embedder: EmbeddingClient, user: UserResponse, *, query: str, scope: str, kind: str,
    product_id: int | None, subject_id: int | None, top_k: int, min_score: float,
) -> SearchOutcome:
    label = SCOPE_LABELS[scope]
    versions = await scoped_versions(db, user, scope, kind, product_id, subject_id)
    if versions is None:
        await db.commit()
        return SearchOutcome("no_consent_record" if scope == "my_contract" else "no_terms", label)
    by_id = {v.terms_version_id: v for v in versions}
    ids = list(by_id)

    generation = await active_generation(db)
    if generation is None or (generation.embedding_model, generation.dimensions) != (embedder.model_id, embedder.dimensions):
        await db.commit()
        raise NOT_READY
    ready = set(await db.scalars(select(TermsIndexEntry.terms_version_id).where(
        TermsIndexEntry.generation_id == generation.generation_id, TermsIndexEntry.status == "ready",
        TermsIndexEntry.terms_version_id.in_(ids),
    )))
    if ready != set(ids):
        await db.commit()
        raise NOT_READY  # 새 버전이 아직 색인되지 않았어도 옛 버전으로 대신하지 않는다
    gen_id = generation.generation_id
    pg = db.bind.dialect.name == "postgresql"
    rows = [] if pg else list(await db.scalars(select(TermsChunk).where(
        TermsChunk.generation_id == gen_id, TermsChunk.terms_version_id.in_(ids)
    )))
    await db.commit()  # 커넥션 반납 후 임베딩을 기다린다

    try:
        (qv,) = await embedder.embed([query], "query")
    except EmbeddingError:
        raise ApiException(503, "TERMS_SEARCH_UNAVAILABLE", "약관 검색을 지금 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.") from None

    if pg:
        distance = TermsChunk.embedding.op("<=>", return_type=Float)(cast(literal(qv, Vector()), Vector()))
        result = await db.execute(
            select(TermsChunk, (1 - distance).label("score"))
            .where(TermsChunk.generation_id == gen_id, TermsChunk.terms_version_id.in_(ids))
            .order_by(distance).limit(CANDIDATES)
        )
        scored = [(c, float(s)) for c, s in result.all()]
        await db.commit()
    else:
        scored = [(c, cosine(qv, c.embedding)) for c in rows]

    candidates = [
        Candidate((c.terms_version_id, c.section_id), s, c.text, c.section_id, c.section_title, c)
        for c, s in scored
    ]
    hits = rank(query, candidates, top_k, min_score)
    if not hits:
        return SearchOutcome("insufficient_evidence", label)
    passages = []
    for h in hits:
        c: TermsChunk = h.payload
        v = by_id[c.terms_version_id]
        passages.append(Passage(
            source_id(v.terms_version_id, c.section_id), v.terms_version_id, v.document_key, v.title, v.version,
            c.section_id, c.section_title, _context(v.body, c.section_id, c.char_start, c.char_end),
            f"/terms/{v.terms_version_id}#{c.section_id}",
        ))
    return SearchOutcome("ok", label, passages)
