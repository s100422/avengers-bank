"""약관 열람·가입 당시 약관 조회 (C-075). AI·임베딩을 쓰지 않아서 AI 장애 중에도 동작한다."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.exceptions import NotFoundException
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.terms import service
from avengers_bank.domains.terms.markdown import parse_sections
from avengers_bank.domains.terms.models import TermsVersion
from avengers_bank.domains.terms.schemas import (
    ConsentItemResponse,
    ConsentRecordResponse,
    ProductTermsResponse,
    TermsItemResponse,
    TermsSectionResponse,
    TermsVersionResponse,
)
from avengers_bank.domains.users.schemas import UserResponse

router = APIRouter(prefix="/terms", tags=["terms (약관)"], responses=error_responses(422))

DbSession = Annotated[AsyncSession, Depends(get_db)]
Kind = Literal["checking", "deposit", "savings", "credit", "debit"]


@router.get(
    "/products/{kind}/{product_id}",
    response_model=SuccessResponse[ProductTermsResponse],
    responses=error_responses(404, 409),
)
async def get_product_terms(kind: Kind, product_id: int, db: DbSession):
    """지금 이 상품에 가입할 때 동의할 약관 목록. 가입 요청에 revision_id·set_hash를 그대로 돌려보낸다."""
    product = await service.find_product(db, kind, product_id)
    if product is None:
        raise NotFoundException(code="PRODUCT_NOT_FOUND", message="상품을 찾을 수 없습니다.")
    current = await service.require_current_set(db, kind, product_id)
    return SuccessResponse[ProductTermsResponse](data=ProductTermsResponse(
        product_kind=kind, product_id=product_id, product_code=product.product_code,
        revision_id=current.revision_id, set_hash=current.set_hash,
        items=[
            TermsItemResponse(
                terms_version_id=i.version.terms_version_id, document_key=i.version.document_key,
                title=i.version.title, version=i.version.version, effective_from=i.version.effective_from,
                required=i.required, order=i.order,
            )
            for i in current.items
        ],
    ))


@router.get(
    "/versions/{terms_version_id}",
    response_model=SuccessResponse[TermsVersionResponse],
    responses=error_responses(404),
)
async def get_terms_version(terms_version_id: int, db: DbSession):
    """저장된 그 버전의 전체 원문 (검색 결과가 아니다)."""
    v = await db.get(TermsVersion, terms_version_id)
    if v is None:
        raise NotFoundException(code="TERMS_NOT_FOUND", message="약관을 찾을 수 없습니다.")
    return SuccessResponse[TermsVersionResponse](data=TermsVersionResponse(
        terms_version_id=v.terms_version_id, document_key=v.document_key, title=v.title, version=v.version,
        effective_from=v.effective_from, status=v.status, body=v.body, body_sha256=v.body_sha256,
        sections=[TermsSectionResponse(section_id=s.section_id, title=s.title) for s in parse_sections(v.body)],
    ))


@router.get(
    "/consents/{kind}/{subject_id}",
    response_model=SuccessResponse[ConsentRecordResponse],
    responses=error_responses(401, 404),
)
async def get_consent_record(
    kind: Kind, subject_id: int, db: DbSession, user: Annotated[UserResponse, Depends(get_current_user)]
):
    """내 계좌·카드의 가입 당시 약관 동의 기록. 약관 기능 전에 가입했으면 has_record=false."""
    records = await service.get_consent_record(db, user, kind, subject_id)
    return SuccessResponse[ConsentRecordResponse](data=ConsentRecordResponse(
        subject_kind=kind, subject_id=subject_id, has_record=bool(records),
        recorded_at=records[0].consent.recorded_at if records else None,
        items=[
            ConsentItemResponse(
                terms_version_id=r.version.terms_version_id, document_key=r.version.document_key,
                title=r.version.title, version=r.version.version, effective_from=r.version.effective_from,
                required=r.consent.required, agreed=r.consent.agreed,
            )
            for r in records
        ],
    ))
