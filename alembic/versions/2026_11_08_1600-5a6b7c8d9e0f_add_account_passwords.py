"""add account passwords (입출금·예금·적금 계좌 비밀번호 숫자 4자리 + 5회 잠금)

Revision ID: 5a6b7c8d9e0f
Revises: 4f2a9c7e1b30
Create Date: 2026-11-08 16:00:00

기존 계좌는 password_hash NULL(미설정)로 둔다. 미설정 계좌는 돈이 나가지 않고(ACCOUNT_PASSWORD_NOT_SET),
휴대폰 인증 후 설정 API(2단계)로 설정한다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '5a6b7c8d9e0f'
down_revision: Union[str, Sequence[str], None] = '4f2a9c7e1b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ('checking_accounts', 'deposit_accounts', 'savings_accounts')


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column('password_hash', sa.String(length=255), nullable=True))
        op.add_column(
            table, sa.Column('password_failed_count', sa.SmallInteger(), server_default='0', nullable=False)
        )
        op.add_column(table, sa.Column('password_locked_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, 'password_locked_at')
        op.drop_column(table, 'password_failed_count')
        op.drop_column(table, 'password_hash')
