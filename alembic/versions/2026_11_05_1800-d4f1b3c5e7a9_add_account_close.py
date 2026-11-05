"""add status/closed_at to deposit and savings accounts, extend history types

Revision ID: d4f1b3c5e7a9
Revises: c3e8a2d4f6b1
Create Date: 2026-11-05 18:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd4f1b3c5e7a9'
down_revision: Union[str, Sequence[str], None] = 'c3e8a2d4f6b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_CHECKING = (
    "'TRANSFER_OUT', 'TRANSFER_IN', 'TO_SAVINGS', 'TO_DEPOSIT', "
    "'CARD_PAYMENT', 'CARD_BILL_PAYMENT', 'DEV_CHARGE'"
)
NEW_CHECKING = OLD_CHECKING + ", 'CLOSE_IN'"
OLD_OTHER = "'TRANSFER_IN'"
NEW_OTHER = "'TRANSFER_IN', 'INTEREST', 'CLOSE_OUT'"
HISTORY_TYPES = {'checking': (OLD_CHECKING, NEW_CHECKING), 'deposit': (OLD_OTHER, NEW_OTHER), 'savings': (OLD_OTHER, NEW_OTHER)}


def _replace_type_checks(index: int) -> None:
    for kind, values in HISTORY_TYPES.items():
        name, table = f'ck_{kind}_account_histories_type', f'{kind}_account_histories'
        op.drop_constraint(name, table, type_='check')
        op.create_check_constraint(name, table, f'type IN ({values[index]})')


def upgrade() -> None:
    for kind in ('deposit', 'savings'):
        table = f'{kind}_accounts'
        # 기존 행은 모두 ACTIVE. 모델에는 DB 기본값이 없으므로 채운 뒤 기본값을 뺀다
        op.add_column(table, sa.Column('status', sa.String(length=10), nullable=False, server_default='ACTIVE'))
        op.alter_column(table, 'status', server_default=None)
        op.add_column(table, sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True))
        op.create_check_constraint(f'ck_{kind}_accounts_status', table, "status IN ('ACTIVE', 'CLOSED')")
        op.create_check_constraint(
            f'ck_{kind}_accounts_closed_at_matches_status', table, "(status = 'CLOSED') = (closed_at IS NOT NULL)"
        )
    _replace_type_checks(1)


def downgrade() -> None:
    _replace_type_checks(0)
    for kind in ('deposit', 'savings'):
        table = f'{kind}_accounts'
        op.drop_constraint(f'ck_{kind}_accounts_closed_at_matches_status', table, type_='check')
        op.drop_constraint(f'ck_{kind}_accounts_status', table, type_='check')
        op.drop_column(table, 'closed_at')
        op.drop_column(table, 'status')
