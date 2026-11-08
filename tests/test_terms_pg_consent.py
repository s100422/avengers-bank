"""약관 발행과 가입이 동시에 일어날 때 (실제 PostgreSQL 행 잠금, C-075).

TEST_PG_DATABASE_URL(예: postgresql+psycopg://postgres:<pw>@127.0.0.1:5435/postgres)이 있을 때만 돈다.
그 서버에 임시 DB를 만들어 쓰고 끝나면 지운다. 개발 DB의 데이터는 건드리지 않는다.
"""

import asyncio
import json
import os
import secrets
import shutil
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from avengers_bank.core.database import Base
from avengers_bank.core.exceptions import ConflictException
from avengers_bank.domains.products.models import AccountProduct
from avengers_bank.domains.terms import service as terms_service
from avengers_bank.domains.terms.loader import load_corpus
from avengers_bank.domains.terms.publish import publish_corpus
from avengers_bank.domains.terms.schemas import TermsConsentIn
from avengers_bank.domains.users.models import User
from avengers_bank.domains.users.schemas import UserResponse

PG_URL = os.environ.get("TEST_PG_DATABASE_URL")
pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(not PG_URL, reason="TEST_PG_DATABASE_URL이 없으면 PostgreSQL 통합 테스트를 건너뛴다"),
]
FIXTURE = Path(__file__).parent / "fixtures" / "terms"
USER = UserResponse.model_construct(user_id=1, login_id="u", name="u", phone="010-0000-0000")


@pytest.fixture
def anyio_backend():
    # Windows 기본 Proactor 루프에서는 psycopg 비동기가 동작하지 않는다
    if sys.platform == "win32":
        return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}
    return "asyncio"


def _write_manifest(root: Path, edit) -> None:
    m = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    edit(m)
    (root / "manifest.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def corpora(tmp_path):
    """(v1, v2) 계좌 상품만 연결한 fixture. v2는 t.account만 2.0.0으로 올렸다."""
    v1 = tmp_path / "v1"
    shutil.copytree(FIXTURE, v1)
    _write_manifest(v1, lambda m: m.update(products=[p for p in m["products"] if p["kind"] not in ("credit", "debit")]))
    v2 = tmp_path / "v2"
    shutil.copytree(v1, v2)
    doc = v2 / "corpus" / "t.account.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace('"version": "1.0.0"', '"version": "2.0.0"') + "바뀐 조항\n",
                   encoding="utf-8")

    def bump(m):
        for item in [*m["documents"], *(t for p in m["products"] for t in p["terms"])]:
            if item["document_key"] == "t.account":
                item["version"] = "2.0.0"

    _write_manifest(v2, bump)
    return load_corpus(v1), load_corpus(v2)


@pytest.fixture
async def pg(corpora):
    admin = create_async_engine(PG_URL, isolation_level="AUTOCOMMIT")
    name = f"ab_test_{secrets.token_hex(4)}"
    async with admin.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_async_engine(make_url(PG_URL).set(database=name))
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db, db.begin():
            db.add(User(login_id="u", hashed_password="x", name="u", phone="010-0000-0000"))
            db.add_all([AccountProduct(type=t, name=t, description="d", interest_rate=1)
                        for t in ("CHECKING", "DEPOSIT", "SAVINGS")])
        async with sessions() as db, db.begin():
            await publish_corpus(db, corpora[0], date(2026, 11, 10))
        yield sessions
    finally:
        await engine.dispose()
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()


async def _seen_terms(sessions) -> TermsConsentIn:
    """사용자가 가입 화면에서 본 예금 상품(2)의 약관 집합에 모두 동의한 값."""
    async with sessions() as db:
        current = await terms_service.get_current_set(db, "deposit", 2)
    return TermsConsentIn(
        revision_id=current.revision_id, set_hash=current.set_hash,
        agreements=[{"terms_version_id": i.version.terms_version_id, "agreed": True} for i in current.items],
    )


async def _still_waiting(task) -> bool:
    await asyncio.sleep(0.5)
    return not task.done()


async def test_signup_waits_for_concurrent_publish_then_requires_reconsent(pg, corpora):
    seen = await _seen_terms(pg)
    pub = pg()
    await pub.begin()
    await publish_corpus(pub, corpora[1], date(2026, 11, 20))  # 아직 커밋 전: 상품 행 FOR UPDATE 보유

    async def signup():
        async with pg() as db, db.begin():
            return await terms_service.check_consent(db, "deposit", 2, seen)

    task = asyncio.create_task(signup())
    assert await _still_waiting(task)
    await pub.commit()
    await pub.close()
    with pytest.raises(ConflictException) as e:
        await task
    assert e.value.code == "TERMS_OUTDATED"


async def test_publish_waits_for_inflight_signup_which_keeps_seen_version(pg, corpora):
    seen = await _seen_terms(pg)
    sign = pg()
    await sign.begin()
    current, agreed = await terms_service.check_consent(sign, "deposit", 2, seen)  # FOR SHARE 보유

    async def publish_v2():
        async with pg() as db, db.begin():
            return await publish_corpus(db, corpora[1], date(2026, 11, 20))

    task = asyncio.create_task(publish_v2())
    assert await _still_waiting(task)
    await terms_service.record_consent(sign, USER, "deposit", 1, current, agreed)
    await sign.commit()
    await sign.close()
    assert "t.account@2.0.0" in (await task).inserted

    async with pg() as db:
        recorded = (await db.execute(text(
            "SELECT v.version FROM terms_consents c JOIN terms_versions v USING (terms_version_id) "
            "WHERE c.subject_kind = 'deposit' AND c.subject_id = 1"
        ))).scalars().all()
        latest = await terms_service.get_current_set(db, "deposit", 2)
    assert recorded == ["1.0.0", "1.0.0"]  # 가입은 사용자가 본 v1 집합으로 기록된다
    assert "2.0.0" in {i.version.version for i in latest.items}
