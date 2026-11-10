"""merchant_categories.prompt_version: reclassify merchants when the classification prompt changes (C-119)

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-11-11 18:00:00

기존 행은 1(첫 지침)로 채운다. 지금 지침 버전(2)과 다르므로 다음 조회 때 다시 분류된다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, Sequence[str], None] = 'a6b7c8d9e0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'merchant_categories',
        sa.Column('prompt_version', sa.SmallInteger(), server_default='1', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('merchant_categories', 'prompt_version')
