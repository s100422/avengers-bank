"""add history type check constraints

Revision ID: a1c8e3f5b2d4
Revises: 6e15576e9ff5
Create Date: 2026-11-05 15:00:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a1c8e3f5b2d4'
down_revision: Union[str, Sequence[str], None] = '6e15576e9ff5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 값 목록은 accounts/kinds.py, cards/kinds.py의 type 상수와 같아야 한다
CHECKING_TYPES = (
    "'TRANSFER_OUT', 'TRANSFER_IN', 'TO_SAVINGS', 'TO_DEPOSIT', "
    "'CARD_PAYMENT', 'CARD_BILL_PAYMENT', 'DEV_CHARGE'"
)
CHECKS = {
    'checking': CHECKING_TYPES,
    'deposit': "'TRANSFER_IN'",
    'savings': "'TRANSFER_IN'",
}


def upgrade() -> None:
    for kind, values in CHECKS.items():
        op.create_check_constraint(
            f'ck_{kind}_account_histories_type', f'{kind}_account_histories', f'type IN ({values})'
        )


def downgrade() -> None:
    for kind in CHECKS:
        op.drop_constraint(f'ck_{kind}_account_histories_type', f'{kind}_account_histories', type_='check')
