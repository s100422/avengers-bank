"""add favorite_accounts (이체 화면의 자주 쓰는 계좌)

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-11-09 14:00:00

사용자별 (은행, 계좌번호) 하나. bank_code가 ''이면 우리 은행이다 (NULL이면 PostgreSQL 유니크가 NULL끼리 다르게 본다).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'a0b1c2d3e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'favorite_accounts',
        sa.Column('favorite_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('bank_code', sa.String(length=3), nullable=False),
        sa.Column('bank_name', sa.String(length=50), nullable=False),
        sa.Column('account', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id']),
        sa.PrimaryKeyConstraint('favorite_id'),
        sa.UniqueConstraint('user_id', 'bank_code', 'account', name='uq_favorite_accounts_user_bank_account'),
    )
    op.create_index('ix_favorite_accounts_user_id', 'favorite_accounts', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_favorite_accounts_user_id', table_name='favorite_accounts')
    op.drop_table('favorite_accounts')
