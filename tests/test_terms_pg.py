"""약관 검색의 PostgreSQL(pgvector) 경로 (C-075). TEST_PG_DATABASE_URL이 있을 때만 돈다.

    TEST_PG_DATABASE_URL=postgresql+psycopg://postgres:<pw>@127.0.0.1:5435/postgres uv run pytest tests/test_terms_pg.py

그 서버에 임시 데이터베이스(terms_pg_test_xxxx)를 만들어 쓰고 끝나면 지운다. 기존 DB의 데이터는 건드리지 않는다.
CREATEDB 권한과 pgvector 확장이 설치된 서버가 필요하다.
"""

import asyncio
import os
import secrets
import sys
from datetime import date

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from avengers_bank.core.database import Base
from avengers_bank.domains.products.models import AccountProduct, CardProduct
from avengers_bank.domains.terms.indexing import index_terms
from avengers_bank.domains.terms.loader import load_corpus
from avengers_bank.domains.terms.models import TermsChunk
from avengers_bank.domains.terms.publish import publish_corpus
from avengers_bank.domains.terms.search import search_terms
from tests.test_terms_rag import CREDIT, FIXTURE, TopicEmbedder

URL = os.environ.get("TEST_PG_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_PG_DATABASE_URL이 없어 PostgreSQL 테스트를 건너뜀")


@pytest.fixture
def pg_url():
    name = f"terms_pg_test_{secrets.token_hex(4)}"
    admin = create_engine(make_url(URL).set(drivername="postgresql+psycopg"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(URL).set(drivername="postgresql+psycopg", database=name)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


async def _scenario(url):
    engine = create_async_engine(url)
    sessions = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
        async with sessions() as db, db.begin():
            db.add_all([AccountProduct(type=t, name=t, description="d", interest_rate=1) for t in ("CHECKING", "DEPOSIT", "SAVINGS")])
            db.add(AccountProduct(type="DEPOSIT", name="RAG 테스트 예금", description="d", interest_rate=3))
            db.add(CardProduct(type="CREDIT", name="RAG 테스트 신용카드", description="d", credit_limit=1_000_000))
        async with sessions() as db, db.begin():
            await publish_corpus(db, load_corpus(FIXTURE), date(2026, 11, 10))

        e = TopicEmbedder()
        first = await index_terms(sessions, e, model_id=e.model_id, dimensions=e.dimensions)
        again = await index_terms(sessions, e, model_id=e.model_id, dimensions=e.dimensions)
        assert first.activated and not first.failed and again.indexed == []
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(TermsChunk)) == first.chunks
            assert await db.scalar(text("SELECT vector_dims(embedding) FROM terms_chunks LIMIT 1")) == 7

        async with sessions() as db:
            dep = await search_terms(db, e, None, query="중도해지하면?", scope="current", kind="deposit",
                                     product_id=4, subject_id=None, top_k=5, min_score=0.5)
            card = await search_terms(db, e, None, query="중도해지하면?", scope="current", kind="credit",
                                      product_id=CREDIT, subject_id=None, top_k=5, min_score=0.5)
            none = await search_terms(db, e, None, query="분실 신고", scope="current", kind="credit",
                                      product_id=CREDIT, subject_id=None, top_k=5, min_score=0.5)
        assert (dep.passages[0].document_key, dep.passages[0].section_id) == ("r.deposit.rules", "early-close")
        assert {p.document_key for p in dep.passages} <= {"r.common", "r.deposit.rules", "r.product.deposit-a"}
        assert [(p.document_key, p.section_id) for p in card.passages] == [("r.credit.rules", "early-close")]
        assert none.status == "insufficient_evidence"
    finally:
        await engine.dispose()


def test_pgvector_index_and_scoped_search(pg_url):
    # Windows 기본 Proactor 루프에서는 psycopg 비동기가 동작하지 않는다
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(_scenario(pg_url), loop_factory=loop_factory)
