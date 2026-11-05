"""add status to credit and debit cards

Revision ID: e5a2c4d6f8b0
Revises: d4f1b3c5e7a9
Create Date: 2026-11-05 19:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e5a2c4d6f8b0'
down_revision: Union[str, Sequence[str], None] = 'd4f1b3c5e7a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = {'credit_cards': 'ck_credit_cards_status', 'debit_cards': 'ck_debit_cards_status'}


def upgrade() -> None:
    for table, name in TABLES.items():
        # 기존 카드는 모두 ACTIVE. 모델에는 DB 기본값이 없으므로 채운 뒤 기본값을 뺀다
        op.add_column(table, sa.Column('status', sa.String(length=10), nullable=False, server_default='ACTIVE'))
        op.alter_column(table, 'status', server_default=None)
        op.create_check_constraint(name, table, "status IN ('ACTIVE', 'SUSPENDED', 'CLOSED')")


def downgrade() -> None:
    for table, name in TABLES.items():
        op.drop_constraint(name, table, type_='check')
        op.drop_column(table, 'status')
