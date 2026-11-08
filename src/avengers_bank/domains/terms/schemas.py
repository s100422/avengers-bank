from datetime import date, datetime

from pydantic import BaseModel, Field, StrictBool


# ── 가입 요청에 붙는 동의 (계좌 3종·카드 2종 공통) ─────────────────────────


class TermsAgreement(BaseModel):
    terms_version_id: int
    agreed: StrictBool  # "true" 같은 문자열을 동의로 받지 않는다


class TermsConsentIn(BaseModel):
    """사용자가 화면에서 본 약관 집합(revision_id·set_hash)과 항목별 동의. 집합의 모든 항목을 한 번씩 보낸다."""

    revision_id: int
    set_hash: str = Field(min_length=1, max_length=64)
    agreements: list[TermsAgreement] = Field(min_length=1, max_length=50)


# ── 응답 ──────────────────────────────────────────────────────────────


class TermsItemResponse(BaseModel):
    terms_version_id: int
    document_key: str
    title: str
    version: str
    effective_from: date
    required: bool
    order: int


class ProductTermsResponse(BaseModel):
    product_kind: str
    product_id: int
    product_code: str | None
    revision_id: int
    set_hash: str
    items: list[TermsItemResponse]


class TermsSectionResponse(BaseModel):
    section_id: str
    title: str


class TermsVersionResponse(BaseModel):
    terms_version_id: int
    document_key: str
    title: str
    version: str
    effective_from: date
    status: str
    demo_only: bool = True
    body: str
    body_sha256: str
    sections: list[TermsSectionResponse]


class ConsentItemResponse(BaseModel):
    terms_version_id: int
    document_key: str
    title: str
    version: str
    effective_from: date
    required: bool
    agreed: bool


class ConsentRecordResponse(BaseModel):
    subject_kind: str
    subject_id: int
    has_record: bool  # false = 약관 기능 도입 전 가입 (동의 기록 없음)
    recorded_at: datetime | None
    items: list[ConsentItemResponse]
