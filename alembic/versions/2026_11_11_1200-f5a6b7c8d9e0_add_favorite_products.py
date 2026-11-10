"""add favorite_products (상품 화면·홈의 찜, C-117)

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-11-11 12:00:00

사용자별 (상품 종류, 상품 id) 하나. 계좌·카드 상품은 테이블이 달라 FK 없이 종류와 함께 저장한다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f5a6b7c8d9e0'
down_revision: Union[str, Sequence[str], None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'favorite_products',
        sa.Column('favorite_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('product_type', sa.String(length=20), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "product_type IN ('CHECKING', 'DEPOSIT', 'SAVINGS', 'CREDIT', 'DEBIT')", name='ck_favorite_products_type'
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id']),
        sa.PrimaryKeyConstraint('favorite_id'),
        sa.UniqueConstraint('user_id', 'product_type', 'product_id', name='uq_favorite_products_user_product'),
    )
    op.create_index('ix_favorite_products_user_id', 'favorite_products', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_favorite_products_user_id', table_name='favorite_products')
    op.drop_table('favorite_products')
