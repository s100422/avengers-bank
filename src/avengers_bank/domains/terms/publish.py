"""약관 발행: docs/terms의 초안을 검증해 DB에 불변 스냅샷으로 저장하고 상품별 적용 집합을 갱신한다 (C-075).

    uv run python -m avengers_bank.domains.terms.publish --effective-from 2026-11-10 --dry-run
    uv run python -m avengers_bank.domains.terms.publish --effective-from 2026-11-10

- 같은 (document_key, version)이 이미 있으면 본문 해시가 같을 때만 그대로 둔다. 다르면 오류(버전을 올려야 한다).
- 상품은 product_code로 찾고, 코드가 없는 상품은 (종류, seed_name)이 정확히 1개 맞을 때만 코드를 저장해 연결한다.
- 적용 집합(문서·버전·본문 해시·필수·순서)이 바뀐 상품만 revision을 하나 더 쌓는다. 같은 입력으로 다시 돌려도 바뀌는 것이 없다.
- 발행과 색인은 별개다. 발행 뒤 indexing 명령을 돌려야 새 버전이 검색된다.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.terms.loader import Corpus, TermsSourceError, load_corpus
from avengers_bank.domains.terms.markdown import sha256
from avengers_bank.domains.terms.models import ProductTermsItem, ProductTermsRevision, TermsVersion
from avengers_bank.domains.terms.service import PRODUCTS, find_product, latest_revision


@dataclass
class PublishReport:
    inserted: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    mapped: list[str] = field(default_factory=list)  # 이번에 product_code를 새로 저장한 상품
    revisions: list[str] = field(default_factory=list)  # 적용 집합이 새로 생긴 상품
    retired: list[str] = field(default_factory=list)


async def _publish_documents(db, corpus, effective_from, report, errors) -> dict[tuple[str, str], TermsVersion]:
    versions = {}
    for (key, ver), doc in sorted(corpus.documents.items()):
        existing = await db.scalar(
            select(TermsVersion).where(TermsVersion.document_key == key, TermsVersion.version == ver)
        )
        if existing is not None:
            if existing.body_sha256 != doc.body_sha256 or existing.title != doc.title:
                errors.append(f"{key}@{ver}: 이미 발행된 버전과 내용이 다릅니다. version을 올려 새로 발행하세요.")
            else:
                report.unchanged.append(f"{key}@{ver}")
            versions[(key, ver)] = existing
            continue
        v = TermsVersion(
            document_key=key, version=ver, title=doc.title, document_type=doc.document_type,
            effective_from=doc.effective_from or effective_from, status="published",
            body=doc.body, body_sha256=doc.body_sha256, meta=doc.meta,
        )
        db.add(v)
        await db.flush()
        versions[(key, ver)] = v
        report.inserted.append(f"{key}@{ver}")
    return versions


async def _publish_products(db, corpus, versions, report, errors) -> None:
    for spec in corpus.products:
        model, type_, _ = PRODUCTS[spec.kind]
        product = await db.scalar(select(model).where(model.product_code == spec.product_code))
        if product is None:
            matches = list(await db.scalars(
                select(model).where(model.type == type_, model.name == spec.seed_name, model.product_code.is_(None))
            ))
            if len(matches) != 1:
                errors.append(f"{spec.product_code}: ({spec.kind}, {spec.seed_name!r}) 상품이 {len(matches)}개입니다. 정확히 1개여야 합니다.")
                continue
            product = matches[0]
            product.product_code = spec.product_code
            report.mapped.append(f"{spec.product_code} → {spec.kind}#{product.product_id}")
        elif product.type != type_:
            errors.append(f"{spec.product_code}: DB 상품 종류({product.type})가 manifest({spec.kind})와 다릅니다.")
            continue
        # 같은 상품의 가입(FOR SHARE)과 겹치지 않게 잠근다
        await find_product(db, spec.kind, product.product_id, lock="update")

        items = [(versions[(t.document_key, t.version)], t) for t in spec.terms]
        set_hash = sha256(json.dumps(
            [[t.document_key, t.version, v.body_sha256, t.required, t.order] for v, t in items], ensure_ascii=False
        ))
        latest = await latest_revision(db, spec.kind, product.product_id)
        if latest is not None and latest.set_hash == set_hash:
            continue
        revision = ProductTermsRevision(
            product_kind=spec.kind, product_id=product.product_id,
            revision=(latest.revision + 1) if latest else 1, set_hash=set_hash,
        )
        db.add(revision)
        await db.flush()
        db.add_all([
            ProductTermsItem(revision_id=revision.revision_id, terms_version_id=v.terms_version_id,
                             required=t.required, display_order=t.order)
            for v, t in items
        ])
        report.revisions.append(f"{spec.product_code} rev {revision.revision}")
    await db.flush()


async def _refresh_statuses(db, report) -> None:
    """현재 적용 집합 어디에도 없는 버전은 retired, 있으면 published (기록·원문은 지우지 않는다)."""
    latest: dict[tuple[str, int], ProductTermsRevision] = {}
    for r in await db.scalars(select(ProductTermsRevision)):
        key = (r.product_kind, r.product_id)
        if key not in latest or r.revision > latest[key].revision:
            latest[key] = r
    current_ids = set(await db.scalars(
        select(ProductTermsItem.terms_version_id)
        .where(ProductTermsItem.revision_id.in_([r.revision_id for r in latest.values()] or [-1]))
    ))
    for v in await db.scalars(select(TermsVersion).where(TermsVersion.status == "published")):
        if v.terms_version_id not in current_ids:
            report.retired.append(f"{v.document_key}@{v.version}")
    await db.execute(
        update(TermsVersion).where(TermsVersion.terms_version_id.not_in(current_ids or {-1}))
        .values(status="retired").execution_options(synchronize_session=False)
    )
    await db.execute(
        update(TermsVersion).where(TermsVersion.terms_version_id.in_(current_ids or {-1}))
        .values(status="published").execution_options(synchronize_session=False)
    )


async def publish_corpus(db: AsyncSession, corpus: Corpus, effective_from: date) -> PublishReport:
    """호출한 쪽이 트랜잭션을 연다. 오류가 하나라도 있으면 TermsSourceError (호출한 쪽이 롤백)."""
    report, errors = PublishReport(), []
    versions = await _publish_documents(db, corpus, effective_from, report, errors)
    if not errors:
        await _publish_products(db, corpus, versions, report, errors)
    if errors:
        raise TermsSourceError(errors)
    await _refresh_statuses(db, report)
    return report


async def _main(args) -> int:
    from avengers_bank.core.database import SessionLocal, engine

    try:
        corpus = load_corpus(args.root)
        async with SessionLocal() as db:
            await db.begin()
            report = await publish_corpus(db, corpus, args.effective_from)
            await (db.rollback() if args.dry_run else db.commit())
    except TermsSourceError as e:
        print("발행 실패 (아무것도 저장하지 않았습니다):", *[f"  - {m}" for m in e.errors], sep="\n")
        return 1
    finally:
        await engine.dispose()
    label = "[dry-run] 저장하지 않음" if args.dry_run else "저장 완료"
    print(f"{label}: 문서 {len(corpus.documents)}개, 상품 {len(corpus.products)}개")
    for name in ("inserted", "unchanged", "mapped", "revisions", "retired"):
        values = getattr(report, name)
        print(f"  {name}: {len(values)}", *[f"    {v}" for v in values], sep="\n")
    if report.inserted and not args.dry_run:
        print("새 버전은 아직 검색되지 않습니다. 색인: uv run python -m avengers_bank.domains.terms.indexing")
    return 0


def main() -> None:
    from avengers_bank.core.config import get_settings

    parser = argparse.ArgumentParser(description="약관 초안을 검증하고 발행한다.")
    parser.add_argument("--root", default=get_settings().terms_root)
    parser.add_argument("--effective-from", required=True, type=date.fromisoformat,
                        help="시행일 (YYYY-MM-DD). 문서에 effective_from이 있으면 그 값을 쓴다")
    parser.add_argument("--dry-run", action="store_true", help="검증과 변경 내역만 보여 주고 저장하지 않는다")
    args = parser.parse_args()
    # Windows 기본 Proactor 루프에서는 psycopg 비동기가 동작하지 않는다
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    sys.exit(asyncio.run(_main(args), loop_factory=loop_factory))


if __name__ == "__main__":
    main()
