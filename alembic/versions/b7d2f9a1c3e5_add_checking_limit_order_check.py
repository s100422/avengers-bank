"""add checking account limit order check

Revision ID: b7d2f9a1c3e5
Revises: a1c8e3f5b2d4
Create Date: 2026-11-05 16:00:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b7d2f9a1c3e5'
down_revision: Union[str, Sequence[str], None] = 'a1c8e3f5b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        'ck_checking_accounts_limit_order', 'checking_accounts',
        'per_transfer_limit <= daily_transfer_limit',
    )


def downgrade() -> None:
    op.drop_constraint('ck_checking_accounts_limit_order', 'checking_accounts', type_='check')
