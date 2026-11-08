"""add account_products.min_amount (예금 상품별 최소 가입 금액)

값 채우기는 마이그레이션이 아니라 seed.py 가 한다.

Revision ID: b8d5f7a9c1e3
Revises: a7c4e6f8b0d2
Create Date: 2026-11-08 10:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b8d5f7a9c1e3'
down_revision: Union[str, Sequence[str], None] = 'a7c4e6f8b0d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('account_products', sa.Column('min_amount', sa.BigInteger(), nullable=True))
    op.create_check_constraint(
        'ck_account_products_min_amount_positive', 'account_products',
        'min_amount IS NULL OR min_amount > 0',
    )


def downgrade() -> None:
    op.drop_constraint('ck_account_products_min_amount_positive', 'account_products', type_='check')
    op.drop_column('account_products', 'min_amount')
