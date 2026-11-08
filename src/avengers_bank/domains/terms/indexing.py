"""약관 검색 색인 (C-075). DB에 발행된 약관 스냅샷(terms_versions)만 색인한다.

    uv run python -m avengers_bank.domains.terms.indexing [--dry-run] [--reindex]

- 세대(generation) = (임베딩 모델, 차원, CHUNKER_VERSION). 활성 세대와 같으면 그 세대에 이어서 색인한다:
  이미 ready인 버전은 건너뛰고(다시 임베딩하지 않음), 없거나 failed인 버전만 처리한다.
- 설정이 바뀌었거나 --reindex면 building 세대를 새로 만들어 전부 색인하고, 모든 버전이 ready일 때만
  같은 트랜잭션에서 옛 활성 세대를 retired로, 새 세대를 active로 바꾼다. 그 전까지 검색은 옛 세대를 쓴다.
- retired 약관도 색인한다: 가입 당시 동의한 버전(my_contract) 검색에 필요하다.
- 임베딩 API를 기다리는 동안 DB 커넥션·트랜잭션을 잡지 않는다 (읽기 → 세션 닫기 → 임베딩 → 짧은 쓰기 트랜잭션).
- 버전 하나의 청크는 한 트랜잭션에서 (지우고 → 다시 쓰기) 하므로 몇 번 돌려도 중복이 생기지 않는다.
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from avengers_bank.domains.terms.chunking import CHUNKER_VERSION, Chunk, chunk_document
from avengers_bank.domains.terms.embedding import EmbeddingClient, EmbeddingError
from avengers_bank.domains.terms.markdown import TermsFormatError, sha256
from avengers_bank.domains.terms.models import (
    ProductTermsItem,
    ProductTermsRevision,
    TermsChunk,
    TermsIndexEntry,
    TermsIndexGeneration,
    TermsVersion,
)


@dataclass
class IndexReport:
    generation_id: int | None = None
    new_generation: bool = False
    activated: bool = False
    indexed: list[str] = field(default_factory=list)
    chunks: int = 0
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # 발행·상품 매핑 불일치


@dataclass
class _Doc:
    terms_version_id: int
    label: str
    title: str
    body: str


async def active_generation(db: AsyncSession) -> TermsIndexGeneration | None:
    return await db.scalar(select(TermsIndexGeneration).where(TermsIndexGeneration.status == "active"))


async def _consistency(db: AsyncSession) -> list[str]:
    """상품마다 최신 적용 집합의 약관이 모두 published인지 확인한다."""
    latest: dict[tuple[str, int], ProductTermsRevision] = {}
    for r in await db.scalars(select(ProductTermsRevision)):
        key = (r.product_kind, r.product_id)
        if key not in latest or r.revision > latest[key].revision:
            latest[key] = r
    problems = []
    for (kind, pid), r in sorted(latest.items()):
        rows = await db.execute(
            select(TermsVersion.document_key, TermsVersion.version, TermsVersion.status)
            .join(ProductTermsItem, ProductTermsItem.terms_version_id == TermsVersion.terms_version_id)
            .where(ProductTermsItem.revision_id == r.revision_id)
        )
        problems += [f"{kind}#{pid} rev {r.revision}: {k}@{v}가 {s} 상태입니다." for k, v, s in rows if s != "published"]
    return problems


async def _write(session_factory, generation_id: int, doc: _Doc, chunks: list[Chunk], vectors: list[list[float]]) -> None:
    async with session_factory() as db, db.begin():
        await db.execute(delete(TermsChunk).where(
            TermsChunk.generation_id == generation_id, TermsChunk.terms_version_id == doc.terms_version_id
        ))
        db.add_all([
            TermsChunk(
                generation_id=generation_id, terms_version_id=doc.terms_version_id, ordinal=c.ordinal,
                section_id=c.section_id, section_title=c.section_title[:200], heading_path=c.heading_path[:400],
                char_start=c.char_start, char_end=c.char_end, text=c.text, text_sha256=sha256(c.text), embedding=v,
            )
            for c, v in zip(chunks, vectors, strict=True)
        ])
        await _set_entry(db, generation_id, doc.terms_version_id, "ready", len(chunks), None)


async def _set_entry(db: AsyncSession, generation_id: int, version_id: int, status: str, count: int, error: str | None):
    entry = await db.get(TermsIndexEntry, (generation_id, version_id))
    if entry is None:
        db.add(TermsIndexEntry(generation_id=generation_id, terms_version_id=version_id,
                               status=status, chunk_count=count, error=error))
    else:
        entry.status, entry.chunk_count, entry.error = status, count, error


async def index_terms(
    session_factory: async_sessionmaker, embedder: EmbeddingClient | None, *,
    model_id: str, dimensions: int, reindex: bool = False, dry_run: bool = False,
) -> IndexReport:
    """embedder는 dry_run이면 None이어도 된다. model_id·dimensions는 세대를 고르는 값 (embedder와 같아야 한다)."""
    if embedder is not None and (embedder.model_id, embedder.dimensions) != (model_id, dimensions):
        raise ValueError("임베딩 클라이언트와 색인 설정의 모델·차원이 다릅니다.")
    report = IndexReport()
    params = dict(embedding_model=model_id, dimensions=dimensions, chunker_version=CHUNKER_VERSION)

    # 1) 읽기: 대상 버전, 쓸 세대, 이미 ready인 버전
    async with session_factory() as db, db.begin():
        report.problems = await _consistency(db)
        docs = [
            _Doc(v.terms_version_id, f"{v.document_key}@{v.version}", v.title, v.body)
            for v in await db.scalars(select(TermsVersion).order_by(TermsVersion.terms_version_id))
        ]
        active = await active_generation(db)
        reuse_active = active is not None and not reindex and all(getattr(active, k) == p for k, p in params.items())
        generation = active if reuse_active else await db.scalar(
            select(TermsIndexGeneration).filter_by(status="building", **params)
            .order_by(TermsIndexGeneration.generation_id.desc()).limit(1)
        )
        if generation is None and not dry_run:
            generation = TermsIndexGeneration(status="building", **params)
            db.add(generation)
            await db.flush()
            report.new_generation = True
        generation_id = generation.generation_id if generation else None
        ready = set() if generation_id is None else set(await db.scalars(
            select(TermsIndexEntry.terms_version_id).where(
                TermsIndexEntry.generation_id == generation_id, TermsIndexEntry.status == "ready"
            )
        ))
    report.generation_id = generation_id

    # 2) 버전마다: 청킹 → (세션 없이) 임베딩 → 짧은 트랜잭션으로 쓰기
    for doc in docs:
        if doc.terms_version_id in ready:
            report.skipped.append(doc.label)
            continue
        try:
            chunks = chunk_document(doc.title, doc.body)
            if dry_run:
                report.indexed.append(doc.label)
                report.chunks += len(chunks)
                continue
            vectors = await embedder.embed([c.text for c in chunks], "document")
            if len(vectors) != len(chunks) or any(len(v) != dimensions for v in vectors):
                raise EmbeddingError("벡터 개수·차원이 세대 설정과 다릅니다")
            await _write(session_factory, generation_id, doc, chunks, vectors)
        except (EmbeddingError, TermsFormatError) as e:
            report.failed.append(f"{doc.label}: {e}")
            if not dry_run:
                async with session_factory() as db, db.begin():
                    await _set_entry(db, generation_id, doc.terms_version_id, "failed", 0, str(e)[:500])
            continue
        report.indexed.append(doc.label)
        report.chunks += len(chunks)

    # 3) 새 세대는 모든 버전이 ready일 때만 활성화 (옛 세대 retire와 같은 트랜잭션)
    if not dry_run and not reuse_active and not report.failed:
        async with session_factory() as db, db.begin():
            all_ids = set(await db.scalars(select(TermsVersion.terms_version_id)))
            ready_now = set(await db.scalars(select(TermsIndexEntry.terms_version_id).where(
                TermsIndexEntry.generation_id == generation_id, TermsIndexEntry.status == "ready"
            )))
            if all_ids <= ready_now:
                old = await active_generation(db)
                if old is not None:
                    old.status = "retired"
                    await db.flush()  # 활성 세대는 하나만 (부분 유니크 인덱스)
                generation = await db.get(TermsIndexGeneration, generation_id)
                generation.status, generation.activated_at = "active", datetime.now(timezone.utc)
                report.activated = True
    return report


async def _main(args) -> int:
    from avengers_bank.core.config import get_settings
    from avengers_bank.core.database import SessionLocal, engine
    from avengers_bank.core.exceptions import ApiException
    from avengers_bank.domains.terms.embedding import get_embedding_client

    s = get_settings()
    try:
        embedder = None if args.dry_run else get_embedding_client()
        report = await index_terms(
            SessionLocal, embedder, model_id=s.embedding_model, dimensions=s.embedding_dimensions,
            reindex=args.reindex, dry_run=args.dry_run,
        )
    except ApiException as e:
        print(f"색인 실패: {e.message} (GEMINI_API_KEY 확인)")
        return 1
    finally:
        await engine.dispose()
    label = "[dry-run] 임베딩·저장하지 않음" if args.dry_run else "색인"
    print(f"{label}: 세대 {report.generation_id or '(새로 만들 예정)'} "
          f"({s.embedding_model}, {s.embedding_dimensions}차원, {CHUNKER_VERSION})"
          f"{' 새 세대' if report.new_generation else ''}{' → 활성화' if report.activated else ''}")
    print(f"  처리: 문서 {len(report.indexed)}개, 청크 {report.chunks}개")
    print(f"  건너뜀(이미 ready): {len(report.skipped)}개")
    print(f"  실패: {len(report.failed)}개", *[f"    {m}" for m in report.failed], sep="\n")
    print(f"  발행·매핑 불일치: {len(report.problems)}개", *[f"    {m}" for m in report.problems], sep="\n")
    return 1 if report.failed or report.problems else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="발행된 약관을 임베딩해 검색 색인을 만든다.")
    parser.add_argument("--dry-run", action="store_true", help="청킹·검증만 하고 임베딩·저장하지 않는다")
    parser.add_argument("--reindex", action="store_true", help="새 세대를 만들어 전부 다시 색인한다")
    args = parser.parse_args()
    # Windows 기본 Proactor 루프에서는 psycopg 비동기가 동작하지 않는다
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    sys.exit(asyncio.run(_main(args), loop_factory=loop_factory))


if __name__ == "__main__":
    main()
