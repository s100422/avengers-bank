"""add verification_codes, users.phone_verified_at / failed_login_count / login_locked_at

Revision ID: 6b7c8d9e0f1a
Revises: 5a6b7c8d9e0f
Create Date: 2026-11-08 16:10:00

휴대폰 인증번호(C-090)와 은행식 로그인 잠금(5회 연속 실패). 기존 사용자는 phone_verified_at NULL(인증 전 가입),
failed_login_count 0, 잠금 없음으로 시작한다.
purpose 목록은 마이그레이션이 그 시점의 사실을 담아야 하므로 models.PURPOSES를 import하지 않고 그대로 적는다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '6b7c8d9e0f1a'
down_revision: Union[str, Sequence[str], None] = '5a6b7c8d9e0f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'verification_codes',
        sa.Column('verification_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('purpose', sa.String(length=30), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('code_hash', sa.String(length=64), nullable=False),
        sa.Column('attempts', sa.SmallInteger(), server_default='0', nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('SIGNUP_PHONE', 'CHANGE_PHONE', 'PASSWORD_RESET', 'FIND_LOGIN_ID', 'ACCOUNT_PASSWORD_RESET')",
            name='ck_verification_codes_purpose',
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id']),
        sa.PrimaryKeyConstraint('verification_id'),
    )
    op.create_index(
        'ix_verification_codes_phone_purpose_created', 'verification_codes', ['phone', 'purpose', 'created_at']
    )
    op.add_column('users', sa.Column('phone_verified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('failed_login_count', sa.SmallInteger(), server_default='0', nullable=False))
    op.add_column('users', sa.Column('login_locked_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'login_locked_at')
    op.drop_column('users', 'failed_login_count')
    op.drop_column('users', 'phone_verified_at')
    op.drop_index('ix_verification_codes_phone_purpose_created', table_name='verification_codes')
    op.drop_table('verification_codes')
