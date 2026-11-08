"""약관 버전·상품별 적용 집합·가입 동의·검색 색인 (C-075).

- terms_versions: 발행한 약관의 불변 스냅샷. 같은 (document_key, version)의 본문은 덮어쓰지 않는다.
- product_terms_revisions/items: 상품마다 "지금 가입할 때 동의할 약관 집합". 바뀌면 revision을 하나 더 쌓는다.
- terms_consents: 가입 때 서버가 기록한 동의. 과거 기록이 가리키는 버전은 FK(RESTRICT)로 지울 수 없다.
- terms_index_*/terms_chunks: 검색용으로 언제든 다시 만들 수 있는 데이터. 원문·동의 기록을 대신하지 않는다.
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator, UserDefinedType

from avengers_bank.core.database import Base

PRODUCT_KINDS = ("checking", "deposit", "savings", "credit", "debit")
_KINDS_SQL = "('checking', 'deposit', 'savings', 'credit', 'debit')"


class _PgVector(UserDefinedType):
    """pgvector의 vector 타입. 차원은 컬럼에 고정하지 않고 색인 세대(dimensions)로 관리한다."""

    cache_ok = True

    def get_col_spec(self, **kw):
        return "vector"

    def bind_processor(self, dialect):
        return lambda v: None if v is None else "[" + ",".join(repr(float(x)) for x in v) + "]"

    def result_processor(self, dialect, coltype):
        return lambda v: None if v is None else [float(x) for x in v.strip("[]").split(",")]


class Vector(TypeDecorator):
    """PostgreSQL에서는 pgvector, 테스트용 SQLite에서는 JSON 배열로 저장한다."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(_PgVector() if dialect.name == "postgresql" else JSON())


class TermsVersion(Base):
    __tablename__ = "terms_versions"
    __table_args__ = (
        UniqueConstraint("document_key", "version", name="uq_terms_versions_key_version"),
        CheckConstraint("status IN ('published', 'retired')", name="ck_terms_versions_status"),
    )

    terms_version_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_key: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="published")
    body: Mapped[str] = mapped_column(Text, nullable=False)  # front matter를 뺀 정규화 Markdown
    body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False)  # 원본 front matter (source_ids 등)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProductTermsRevision(Base):
    __tablename__ = "product_terms_revisions"
    __table_args__ = (
        UniqueConstraint("product_kind", "product_id", "revision", name="uq_product_terms_revisions"),
        CheckConstraint(f"product_kind IN {_KINDS_SQL}", name="ck_product_terms_revisions_kind"),
    )

    revision_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 계좌 상품과 카드 상품의 product_id는 겹칠 수 있어서 종류와 함께 쓴다 (FK는 종류마다 테이블이 달라 두지 않는다)
    product_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    product_id: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProductTermsItem(Base):
    __tablename__ = "product_terms_items"

    revision_id: Mapped[int] = mapped_column(
        ForeignKey("product_terms_revisions.revision_id"), primary_key=True
    )
    terms_version_id: Mapped[int] = mapped_column(
        ForeignKey("terms_versions.terms_version_id"), primary_key=True
    )
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)


class TermsConsent(Base):
    __tablename__ = "terms_consents"
    __table_args__ = (
        UniqueConstraint("subject_kind", "subject_id", "terms_version_id", name="uq_terms_consents_subject_version"),
        CheckConstraint(f"subject_kind IN {_KINDS_SQL}", name="ck_terms_consents_kind"),
        Index("ix_terms_consents_subject", "subject_kind", "subject_id"),
    )

    consent_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False, index=True)
    subject_kind: Mapped[str] = mapped_column(String(10), nullable=False)  # 가입한 계좌·카드 종류
    subject_id: Mapped[int] = mapped_column(Integer, nullable=False)  # 계좌·카드 ID
    revision_id: Mapped[int] = mapped_column(ForeignKey("product_terms_revisions.revision_id"), nullable=False)
    terms_version_id: Mapped[int] = mapped_column(ForeignKey("terms_versions.terms_version_id"), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    agreed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)  # 동의 당시 본문 해시
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ── 검색 색인 (다시 만들 수 있는 데이터) ─────────────────────────────────


class TermsIndexGeneration(Base):
    """임베딩 모델·차원·청킹 방식이 같은 색인 한 벌. 다 만든 뒤에만 active로 바꾼다."""

    __tablename__ = "terms_index_generations"
    __table_args__ = (
        CheckConstraint("status IN ('building', 'active', 'retired')", name="ck_terms_index_generations_status"),
        CheckConstraint("dimensions > 0", name="ck_terms_index_generations_dimensions"),
        Index(
            "uq_terms_index_generations_active", "status", unique=True,
            postgresql_where=text("status = 'active'"), sqlite_where=text("status = 'active'"),
        ),
    )

    generation_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="building")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TermsIndexEntry(Base):
    """세대 안에서 약관 버전 하나의 색인 상태. ready가 아니면 그 버전은 검색 준비가 안 된 것이다."""

    __tablename__ = "terms_index_entries"
    __table_args__ = (
        CheckConstraint("status IN ('ready', 'failed')", name="ck_terms_index_entries_status"),
    )

    generation_id: Mapped[int] = mapped_column(
        ForeignKey("terms_index_generations.generation_id"), primary_key=True
    )
    terms_version_id: Mapped[int] = mapped_column(
        ForeignKey("terms_versions.terms_version_id"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TermsChunk(Base):
    __tablename__ = "terms_chunks"
    __table_args__ = (
        UniqueConstraint("generation_id", "terms_version_id", "ordinal", name="uq_terms_chunks_position"),
        Index("ix_terms_chunks_generation_version", "generation_id", "terms_version_id"),
    )

    chunk_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    generation_id: Mapped[int] = mapped_column(
        ForeignKey("terms_index_generations.generation_id"), nullable=False
    )
    terms_version_id: Mapped[int] = mapped_column(
        ForeignKey("terms_versions.terms_version_id"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)  # 문서 안 순서
    section_id: Mapped[str] = mapped_column(String(100), nullable=False)  # ## [section-id] 의 id (앵커)
    section_title: Mapped[str] = mapped_column(String(200), nullable=False)
    heading_path: Mapped[str] = mapped_column(String(400), nullable=False)  # "문서 제목 > 조항 제목"
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)  # body 안 위치 [start, end)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)  # 임베딩한 글 (heading_path 포함)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(), nullable=False)
