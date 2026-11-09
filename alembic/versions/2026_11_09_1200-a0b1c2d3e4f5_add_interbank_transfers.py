"""add interbank_transfers, history types INTERBANK_*, counterpart_account 50자

Revision ID: a0b1c2d3e4f5
Revises: 9e0f1a2b3c4d
Create Date: 2026-11-09 12:00:00

ClearingHub 타행 이체 (docs/SPEC.md).
- interbank_transfers: 보낸(OUT)·받은(IN) 타행 이체. transfer_id가 기본키 = 멱등성 키
- checking_account_histories.type에 INTERBANK_OUT / INTERBANK_IN / INTERBANK_REFUND
- counterpart_account를 50자로 (타행 계좌번호 최대 50자). 늘리기만 하므로 기존 값은 그대로다
값 목록은 마이그레이션이 그 시점의 사실을 담아야 하므로 models의 목록을 import하지 않고 그대로 적는다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a0b1c2d3e4f5'
down_revision: Union[str, Sequence[str], None] = '9e0f1a2b3c4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_TYPES = (
    "'TRANSFER_OUT', 'TRANSFER_IN', 'TO_SAVINGS', 'TO_DEPOSIT', "
    "'CARD_PAYMENT', 'CARD_BILL_PAYMENT', 'DEV_CHARGE', 'CLOSE_IN'"
)
NEW_TYPES = OLD_TYPES + ", 'INTERBANK_OUT', 'INTERBANK_IN', 'INTERBANK_REFUND'"


def _type_check(values: str) -> None:
    op.drop_constraint('ck_checking_account_histories_type', 'checking_account_histories', type_='check')
    op.create_check_constraint(
        'ck_checking_account_histories_type', 'checking_account_histories', f"type IN ({values})"
    )


def upgrade() -> None:
    op.create_table(
        'interbank_transfers',
        sa.Column('transfer_id', sa.String(length=36), nullable=False),
        sa.Column('direction', sa.String(length=3), nullable=False),
        sa.Column('checking_account_id', sa.Integer(), nullable=False),
        sa.Column('peer_bank', sa.String(length=3), nullable=False),
        sa.Column('peer_bank_name', sa.String(length=50), nullable=True),
        sa.Column('peer_account', sa.String(length=50), nullable=False),
        sa.Column('peer_name', sa.String(length=100), nullable=True),
        sa.Column('amount', sa.BigInteger(), nullable=False),
        sa.Column('memo', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('fail_code', sa.String(length=40), nullable=True),
        sa.Column('fail_message', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('amount > 0', name='ck_interbank_transfers_amount_positive'),
        sa.CheckConstraint("direction IN ('OUT', 'IN')", name='ck_interbank_transfers_direction'),
        sa.CheckConstraint("status IN ('PENDING', 'COMPLETED', 'FAILED')", name='ck_interbank_transfers_status'),
        sa.ForeignKeyConstraint(['checking_account_id'], ['checking_accounts.checking_account_id']),
        sa.PrimaryKeyConstraint('transfer_id'),
    )
    op.create_index('ix_interbank_transfers_checking_account_id', 'interbank_transfers', ['checking_account_id'])
    op.create_index('ix_interbank_transfers_status', 'interbank_transfers', ['status'])
    _type_check(NEW_TYPES)
    op.alter_column(
        'checking_account_histories', 'counterpart_account',
        existing_type=sa.String(length=20), type_=sa.String(length=50), existing_nullable=True,
    )


def downgrade() -> None:
    # 타행 거래내역이 있으면 옛 제약·20자 열에 맞지 않아 실패한다. 먼저 지우거나 되돌리지 않는다
    op.alter_column(
        'checking_account_histories', 'counterpart_account',
        existing_type=sa.String(length=50), type_=sa.String(length=20), existing_nullable=True,
    )
    _type_check(OLD_TYPES)
    op.drop_index('ix_interbank_transfers_status', table_name='interbank_transfers')
    op.drop_index('ix_interbank_transfers_checking_account_id', table_name='interbank_transfers')
    op.drop_table('interbank_transfers')
