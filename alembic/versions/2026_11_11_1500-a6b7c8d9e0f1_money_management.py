"""money management: merchant category cache, user rules, transaction overrides, recurring items (C-118)

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-11-11 15:00:00

원본 거래는 바꾸지 않고 분석용 정보만 저장한다. 거래는 세 테이블에 나뉘어 있어 (source, source_id)로 가리킨다(FK 없음).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a6b7c8d9e0f1'
down_revision: Union[str, Sequence[str], None] = 'f5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CATEGORY_IN = (
    "IN ('DINING', 'CAFE', 'MART', 'BEAUTY', 'ONLINE', 'SUBSCRIPTION', 'TRANSPORT', 'HOUSING', "
    "'MEDICAL', 'LEISURE', 'TRANSFER', 'ETC', 'UNCLASSIFIED')"
)


def _created_at():
    return sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False)


def upgrade() -> None:
    op.create_table(
        'merchant_categories',
        sa.Column('merchant_key', sa.String(length=100), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('reason', sa.String(length=200), nullable=True),
        _created_at(),
        sa.CheckConstraint(f"category {CATEGORY_IN}", name='ck_merchant_categories_category'),
        sa.PrimaryKeyConstraint('merchant_key'),
    )
    op.create_table(
        'money_category_rules',
        sa.Column('rule_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('merchant_key', sa.String(length=100), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        _created_at(),
        sa.CheckConstraint(f"category {CATEGORY_IN}", name='ck_money_category_rules_category'),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id']),
        sa.PrimaryKeyConstraint('rule_id'),
        sa.UniqueConstraint('user_id', 'merchant_key', name='uq_money_category_rules_user_merchant'),
    )
    op.create_index('ix_money_category_rules_user_id', 'money_category_rules', ['user_id'])
    op.create_table(
        'money_transaction_overrides',
        sa.Column('override_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=10), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=True),
        sa.Column('is_one_off', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("source IN ('credit', 'debit', 'checking')", name='ck_money_overrides_source'),
        sa.CheckConstraint(f"category IS NULL OR category {CATEGORY_IN}", name='ck_money_overrides_category'),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id']),
        sa.PrimaryKeyConstraint('override_id'),
        sa.UniqueConstraint('user_id', 'source', 'source_id', name='uq_money_overrides_user_source'),
    )
    op.create_index('ix_money_transaction_overrides_user_id', 'money_transaction_overrides', ['user_id'])
    op.create_table(
        'money_recurring_items',
        sa.Column('recurring_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('merchant_key', sa.String(length=100), nullable=True),
        sa.Column('direction', sa.String(length=3), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=True),
        sa.Column('amount', sa.BigInteger(), nullable=False),
        sa.Column('day_of_month', sa.SmallInteger(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('skip_month', sa.String(length=7), nullable=True),
        _created_at(),
        sa.CheckConstraint("direction IN ('IN', 'OUT')", name='ck_money_recurring_direction'),
        sa.CheckConstraint("status IN ('ACTIVE', 'EXCLUDED', 'DISMISSED')", name='ck_money_recurring_status'),
        sa.CheckConstraint('day_of_month BETWEEN 1 AND 31', name='ck_money_recurring_day'),
        sa.CheckConstraint('amount >= 0', name='ck_money_recurring_amount'),
        sa.CheckConstraint(f"category IS NULL OR category {CATEGORY_IN}", name='ck_money_recurring_category'),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id']),
        sa.PrimaryKeyConstraint('recurring_id'),
    )
    op.create_index('ix_money_recurring_items_user_id', 'money_recurring_items', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_money_recurring_items_user_id', table_name='money_recurring_items')
    op.drop_table('money_recurring_items')
    op.drop_index('ix_money_transaction_overrides_user_id', table_name='money_transaction_overrides')
    op.drop_table('money_transaction_overrides')
    op.drop_index('ix_money_category_rules_user_id', table_name='money_category_rules')
    op.drop_table('money_category_rules')
    op.drop_table('merchant_categories')
