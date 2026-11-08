"""테스트용 약관 도우미 (C-075)."""

from datetime import date

from sqlalchemy import select

from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.terms import service as terms_service
from avengers_bank.domains.terms.markdown import sha256
from avengers_bank.domains.terms.models import ProductTermsItem, ProductTermsRevision, TermsVersion

OPEN_PATHS = {
    "/accounts/checking": "checking",
    "/accounts/deposit": "deposit",
    "/accounts/savings": "savings",
    "/cards/credit": "credit",
    "/cards/debit": "debit",
}
_BODY = "# 테스트 약관\n\n## [scope] 적용 범위\n\n테스트 상품에 적용합니다.\n"


async def ensure_minimal_terms(kind: str, product_id: int) -> bool:
    """상품에 약관 집합이 없으면 필수 약관 1개짜리 집합을 만든다. 상품이 없으면 False."""
    async with SessionLocal() as db, db.begin():
        if await terms_service.find_product(db, kind, product_id) is None:
            return False
        if await terms_service.latest_revision(db, kind, product_id) is not None:
            return True
        version = await db.scalar(select(TermsVersion).where(TermsVersion.document_key == "test.minimal"))
        if version is None:
            version = TermsVersion(
                document_key="test.minimal", version="1.0.0", title="테스트 약관", document_type="common_terms",
                effective_from=date(2026, 1, 1), status="published",
                body=_BODY, body_sha256=sha256(_BODY), meta={},
            )
            db.add(version)
            await db.flush()
        revision = ProductTermsRevision(product_kind=kind, product_id=product_id, revision=1, set_hash="minimal")
        db.add(revision)
        await db.flush()
        db.add(ProductTermsItem(revision_id=revision.revision_id, terms_version_id=version.terms_version_id,
                                required=True, display_order=1))
    return True


async def agree_all(client, kind: str, product_id: int) -> dict:
    """현재 약관 집합에 모두 동의하는 terms 값. 상품이 없으면 형식만 맞춘 값(서비스가 상품 404를 먼저 낸다)."""
    if not await ensure_minimal_terms(kind, product_id):
        return {"revision_id": 0, "set_hash": "none", "agreements": [{"terms_version_id": 0, "agreed": True}]}
    data = (await client.get(f"/terms/products/{kind}/{product_id}")).json()["data"]
    return {
        "revision_id": data["revision_id"], "set_hash": data["set_hash"],
        "agreements": [{"terms_version_id": i["terms_version_id"], "agreed": True} for i in data["items"]],
    }
