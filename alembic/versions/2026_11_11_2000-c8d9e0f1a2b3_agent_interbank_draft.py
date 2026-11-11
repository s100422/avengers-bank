"""agent_transfer_drafts: to_bank for AI interbank transfers, longer account number (C-125)

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-11-11 20:00:00

to_bank가 NULL이면 우리 은행 이체(기존 초안 모두), 값이 있으면 그 은행으로 타행 이체. 타행 계좌번호는 최대 50자(SPEC 3.3).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c8d9e0f1a2b3'
down_revision: Union[str, Sequence[str], None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agent_transfer_drafts', sa.Column('to_bank', sa.String(length=3), nullable=True))
    op.alter_column('agent_transfer_drafts', 'to_account_num', type_=sa.String(length=50), existing_type=sa.String(length=20), existing_nullable=False)


def downgrade() -> None:
    op.alter_column('agent_transfer_drafts', 'to_account_num', type_=sa.String(length=20), existing_type=sa.String(length=50), existing_nullable=False)
    op.drop_column('agent_transfer_drafts', 'to_bank')
