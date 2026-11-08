"""상품별 현재 약관 집합, 가입 동의 검증·기록, 가입 당시 약관 조회 (C-075).

동시성: 가입은 상품 행을 FOR SHARE로, 발행은 FOR UPDATE로 잠근다. 그래서 새 약관 발행과 가입이 겹치면
한쪽이 끝날 때까지 기다리고, 가입은 잠근 뒤에 읽은 "현재 집합"과 사용자가 본 집합을 비교한다.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.exceptions import BadRequestException, ConflictException, NotFoundException
from avengers_bank.domains.accounts.kinds import KINDS as ACCOUNT_KINDS
from avengers_bank.domains.cards.kinds import KINDS as CARD_KINDS
from avengers_bank.domains.products.models import AccountProduct, CardProduct
from avengers_bank.domains.terms.models import ProductTermsItem, ProductTermsRevision, TermsConsent, TermsVersion
from avengers_bank.domains.terms.schemas import TermsConsentIn
from avengers_bank.domains.users.schemas import UserResponse

# kind → (상품 모델, 상품 type 값, 계좌·카드 종류 정보)
PRODUCTS = {
    "checking": (AccountProduct, "CHECKING", ACCOUNT_KINDS["checking"]),
    "deposit": (AccountProduct, "DEPOSIT", ACCOUNT_KINDS["deposit"]),
    "savings": (AccountProduct, "SAVINGS", ACCOUNT_KINDS["savings"]),
    "credit": (CardProduct, "CREDIT", CARD_KINDS["credit"]),
    "debit": (CardProduct, "DEBIT", CARD_KINDS["debit"]),
}


@dataclass
class SetItem:
    version: TermsVersion
    required: bool
    order: int


@dataclass
class CurrentSet:
    revision_id: int
    set_hash: str
    product_kind: str
    product_id: int
    items: list[SetItem]


@dataclass
class ConsentRecord:
    consent: TermsConsent
    version: TermsVersion


async def find_product(db: AsyncSession, kind: str, product_id: int, *, lock: str | None = None):
    """종류가 맞는 상품. lock: None / "share"(가입) / "update"(발행)."""
    model, type_, _ = PRODUCTS[kind]
    stmt = select(model).where(model.product_id == product_id, model.type == type_)
    if lock:
        stmt = stmt.with_for_update(read=lock == "share")
    return await db.scalar(stmt)


async def latest_revision(db: AsyncSession, kind: str, product_id: int) -> ProductTermsRevision | None:
    return await db.scalar(
        select(ProductTermsRevision)
        .where(ProductTermsRevision.product_kind == kind, ProductTermsRevision.product_id == product_id)
        .order_by(ProductTermsRevision.revision.desc()).limit(1)
    )


async def get_current_set(db: AsyncSession, kind: str, product_id: int) -> CurrentSet | None:
    """지금 가입할 때 동의할 약관 집합. 발행된 약관이 없으면 None."""
    revision = await latest_revision(db, kind, product_id)
    if revision is None:
        return None
    rows = await db.execute(
        select(ProductTermsItem, TermsVersion)
        .join(TermsVersion, TermsVersion.terms_version_id == ProductTermsItem.terms_version_id)
        .where(ProductTermsItem.revision_id == revision.revision_id)
        .order_by(ProductTermsItem.display_order)
    )
    items = [SetItem(v, i.required, i.display_order) for i, v in rows.all()]
    return CurrentSet(revision.revision_id, revision.set_hash, kind, product_id, items)


async def require_current_set(db: AsyncSession, kind: str, product_id: int) -> CurrentSet:
    current = await get_current_set(db, kind, product_id)
    # 약관이 없는 상품을 조용히 동의 없이 가입시키지 않는다
    if current is None or not any(i.required for i in current.items):
        raise ConflictException(
            code="TERMS_NOT_CONFIGURED", message="이 상품은 약관이 준비되지 않아 지금 가입할 수 없습니다."
        )
    return current


async def check_consent(
    db: AsyncSession, kind: str, product_id: int, consent: TermsConsentIn
) -> tuple[CurrentSet, dict[int, bool]]:
    """가입 트랜잭션 안에서 부른다. 상품 행을 공유 잠금한 뒤 사용자가 본 약관 집합이 아직 현재인지 확인한다."""
    if await find_product(db, kind, product_id, lock="share") is None:
        raise NotFoundException(code="PRODUCT_NOT_FOUND", message="상품을 찾을 수 없습니다.")
    current = await require_current_set(db, kind, product_id)
    if consent.revision_id != current.revision_id or consent.set_hash != current.set_hash:
        raise ConflictException(
            code="TERMS_OUTDATED", message="약관이 변경되었습니다. 최신 약관을 확인하고 다시 동의해 주세요."
        )
    ids = [a.terms_version_id for a in consent.agreements]
    expected = {i.version.terms_version_id for i in current.items}
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise BadRequestException(
            code="TERMS_INVALID", message="약관 동의 항목이 이 상품의 약관과 맞지 않습니다. 화면을 새로고침해 주세요."
        )
    agreed = {a.terms_version_id: a.agreed for a in consent.agreements}
    if any(i.required and not agreed[i.version.terms_version_id] for i in current.items):
        raise BadRequestException(code="TERMS_REQUIRED_NOT_AGREED", message="필수 약관에 모두 동의해야 가입할 수 있습니다.")
    return current, agreed


async def record_consent(
    db: AsyncSession, user: UserResponse, kind: str, subject_id: int, current: CurrentSet, agreed: dict[int, bool]
) -> None:
    """가입과 같은 트랜잭션에서 기록한다. 시각은 서버가 정하고 IP·기기 정보는 받지 않는다."""
    db.add_all([
        TermsConsent(
            user_id=user.user_id, subject_kind=kind, subject_id=subject_id, revision_id=current.revision_id,
            terms_version_id=i.version.terms_version_id, required=i.required,
            agreed=agreed[i.version.terms_version_id], body_sha256=i.version.body_sha256,
        )
        for i in current.items
    ])
    await db.flush()


async def _require_owned(db: AsyncSession, user: UserResponse, kind: str, subject_id: int) -> None:
    info = PRODUCTS[kind][2]
    subject = await db.get(info.model, subject_id)
    # 남의 계좌·카드도 404로 알려서 ID가 있는지 드러나지 않게 한다 (C-031)
    if subject is None or subject.user_id != user.user_id:
        raise NotFoundException(code="SUBJECT_NOT_FOUND", message="계좌 또는 카드를 찾을 수 없습니다.")


async def get_consent_record(
    db: AsyncSession, user: UserResponse, kind: str, subject_id: int
) -> list[ConsentRecord]:
    """가입 당시 동의 기록. 빈 목록 = 약관 기능 도입 전에 가입해서 기록이 없음 (소급 생성하지 않는다)."""
    await _require_owned(db, user, kind, subject_id)
    rows = await db.execute(
        select(TermsConsent, TermsVersion)
        .join(TermsVersion, TermsVersion.terms_version_id == TermsConsent.terms_version_id)
        .join(ProductTermsItem, (ProductTermsItem.revision_id == TermsConsent.revision_id)
              & (ProductTermsItem.terms_version_id == TermsConsent.terms_version_id))
        .where(TermsConsent.subject_kind == kind, TermsConsent.subject_id == subject_id)
        .order_by(ProductTermsItem.display_order)
    )
    return [ConsentRecord(c, v) for c, v in rows.all()]


async def get_consented_versions(
    db: AsyncSession, user: UserResponse, kind: str, subject_id: int
) -> list[TermsVersion] | None:
    """가입 당시 동의한 약관 버전들(동의 거부한 선택 약관은 제외). None = 기록 없음."""
    records = await get_consent_record(db, user, kind, subject_id)
    if not records:
        return None
    return [r.version for r in records if r.consent.agreed]
