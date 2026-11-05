"""rename credit_cards.accumulated_amount to outstanding_amount, add counterpart_name

Revision ID: c3e8a2d4f6b1
Revises: b7d2f9a1c3e5
Create Date: 2026-11-05 17:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c3e8a2d4f6b1'
down_revision: Union[str, Sequence[str], None] = 'b7d2f9a1c3e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('credit_cards', 'accumulated_amount', new_column_name='outstanding_amount')
    op.execute(
        'ALTER TABLE credit_cards RENAME CONSTRAINT ck_credit_cards_accumulated_amount_within_limit '
        'TO ck_credit_cards_outstanding_amount_within_limit'
    )
    op.add_column('checking_account_histories', sa.Column('counterpart_name', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('checking_account_histories', 'counterpart_name')
    op.execute(
        'ALTER TABLE credit_cards RENAME CONSTRAINT ck_credit_cards_outstanding_amount_within_limit '
        'TO ck_credit_cards_accumulated_amount_within_limit'
    )
    op.alter_column('credit_cards', 'outstanding_amount', new_column_name='accumulated_amount')
