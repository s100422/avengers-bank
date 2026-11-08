"""add terms versions, product terms sets, consents, search index (C-075)

pgvector 확장이 필요하다: CREATE EXTENSION은 DB 소유자 또는 슈퍼유저 권한이 있어야 한다 (docs/TERMS_RAG.md).

Revision ID: a7c4e6f8b0d2
Revises: f6b3d5e7a9c1
Create Date: 2026-11-07 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from avengers_bank.domains.terms.models import Vector

revision: str = 'a7c4e6f8b0d2'
down_revision: Union[str, Sequence[str], None] = 'f6b3d5e7a9c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KINDS = "('checking', 'deposit', 'savings', 'credit', 'debit')"


def _now():
    return sa.text('now()')


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 상품의 안정적인 코드. manifest의 product_code와 연결한다 (삽입 순서·숫자 ID에 의존하지 않기 위해)
    op.add_column('account_products', sa.Column('product_code', sa.String(length=50), nullable=True))
    op.create_unique_constraint('uq_account_products_product_code', 'account_products', ['product_code'])
    op.add_column('card_products', sa.Column('product_code', sa.String(length=50), nullable=True))
    op.create_unique_constraint('uq_card_products_product_code', 'card_products', ['product_code'])

    op.add_column('agent_messages', sa.Column('citations', sa.JSON(), nullable=True))

    op.create_table(
        'terms_versions',
        sa.Column('terms_version_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('document_key', sa.String(length=100), nullable=False),
        sa.Column('version', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('document_type', sa.String(length=30), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('body_sha256', sa.String(length=64), nullable=False),
        sa.Column('meta', sa.JSON(), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint("status IN ('published', 'retired')", name='ck_terms_versions_status'),
        sa.PrimaryKeyConstraint('terms_version_id'),
        sa.UniqueConstraint('document_key', 'version', name='uq_terms_versions_key_version'),
    )
    op.create_table(
        'product_terms_revisions',
        sa.Column('revision_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('product_kind', sa.String(length=10), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('set_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint(f"product_kind IN {KINDS}", name='ck_product_terms_revisions_kind'),
        sa.PrimaryKeyConstraint('revision_id'),
        sa.UniqueConstraint('product_kind', 'product_id', 'revision', name='uq_product_terms_revisions'),
    )
    op.create_table(
        'product_terms_items',
        sa.Column('revision_id', sa.Integer(), nullable=False),
        sa.Column('terms_version_id', sa.Integer(), nullable=False),
        sa.Column('required', sa.Boolean(), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['revision_id'], ['product_terms_revisions.revision_id']),
        sa.ForeignKeyConstraint(['terms_version_id'], ['terms_versions.terms_version_id']),
        sa.PrimaryKeyConstraint('revision_id', 'terms_version_id'),
    )
    op.create_table(
        'terms_consents',
        sa.Column('consent_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('subject_kind', sa.String(length=10), nullable=False),
        sa.Column('subject_id', sa.Integer(), nullable=False),
        sa.Column('revision_id', sa.Integer(), nullable=False),
        sa.Column('terms_version_id', sa.Integer(), nullable=False),
        sa.Column('required', sa.Boolean(), nullable=False),
        sa.Column('agreed', sa.Boolean(), nullable=False),
        sa.Column('body_sha256', sa.String(length=64), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint(f"subject_kind IN {KINDS}", name='ck_terms_consents_kind'),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id']),
        sa.ForeignKeyConstraint(['revision_id'], ['product_terms_revisions.revision_id']),
        sa.ForeignKeyConstraint(['terms_version_id'], ['terms_versions.terms_version_id']),
        sa.PrimaryKeyConstraint('consent_id'),
        sa.UniqueConstraint('subject_kind', 'subject_id', 'terms_version_id', name='uq_terms_consents_subject_version'),
    )
    op.create_index('ix_terms_consents_user_id', 'terms_consents', ['user_id'])
    op.create_index('ix_terms_consents_subject', 'terms_consents', ['subject_kind', 'subject_id'])

    op.create_table(
        'terms_index_generations',
        sa.Column('generation_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('embedding_model', sa.String(length=100), nullable=False),
        sa.Column('dimensions', sa.Integer(), nullable=False),
        sa.Column('chunker_version', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('building', 'active', 'retired')", name='ck_terms_index_generations_status'),
        sa.CheckConstraint('dimensions > 0', name='ck_terms_index_generations_dimensions'),
        sa.PrimaryKeyConstraint('generation_id'),
    )
    op.create_index(
        'uq_terms_index_generations_active', 'terms_index_generations', ['status'], unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        'terms_index_entries',
        sa.Column('generation_id', sa.Integer(), nullable=False),
        sa.Column('terms_version_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('chunk_count', sa.Integer(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.CheckConstraint("status IN ('ready', 'failed')", name='ck_terms_index_entries_status'),
        sa.ForeignKeyConstraint(['generation_id'], ['terms_index_generations.generation_id']),
        sa.ForeignKeyConstraint(['terms_version_id'], ['terms_versions.terms_version_id']),
        sa.PrimaryKeyConstraint('generation_id', 'terms_version_id'),
    )
    op.create_table(
        'terms_chunks',
        sa.Column('chunk_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('generation_id', sa.Integer(), nullable=False),
        sa.Column('terms_version_id', sa.Integer(), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('section_id', sa.String(length=100), nullable=False),
        sa.Column('section_title', sa.String(length=200), nullable=False),
        sa.Column('heading_path', sa.String(length=400), nullable=False),
        sa.Column('char_start', sa.Integer(), nullable=False),
        sa.Column('char_end', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('text_sha256', sa.String(length=64), nullable=False),
        sa.Column('embedding', Vector(), nullable=False),
        sa.ForeignKeyConstraint(['generation_id'], ['terms_index_generations.generation_id']),
        sa.ForeignKeyConstraint(['terms_version_id'], ['terms_versions.terms_version_id']),
        sa.PrimaryKeyConstraint('chunk_id'),
        sa.UniqueConstraint('generation_id', 'terms_version_id', 'ordinal', name='uq_terms_chunks_position'),
    )
    op.create_index('ix_terms_chunks_generation_version', 'terms_chunks', ['generation_id', 'terms_version_id'])


def downgrade() -> None:
    op.drop_table('terms_chunks')
    op.drop_table('terms_index_entries')
    op.drop_index('uq_terms_index_generations_active', table_name='terms_index_generations')
    op.drop_table('terms_index_generations')
    op.drop_table('terms_consents')
    op.drop_table('product_terms_items')
    op.drop_table('product_terms_revisions')
    op.drop_table('terms_versions')
    op.drop_column('agent_messages', 'citations')
    op.drop_constraint('uq_card_products_product_code', 'card_products', type_='unique')
    op.drop_column('card_products', 'product_code')
    op.drop_constraint('uq_account_products_product_code', 'account_products', type_='unique')
    op.drop_column('account_products', 'product_code')
    # vector 확장은 다른 곳에서 쓸 수 있어서 지우지 않는다
