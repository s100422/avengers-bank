"""add user_devices (device registration B1), users device-channel lock columns, purpose NEW_DEVICE

Revision ID: 9e0f1a2b3c4d
Revises: 8d9e0f1a2b3c
Create Date: 2026-11-09 10:00:00

기기 등록(B1). 새 기기 로그인은 휴대폰 인증을 더 하고, 통과한 기기는 쿠키로 기억한다.
- user_devices: 등록 기기. 쿠키 원문은 저장하지 않고 SHA-256 해시만(refresh_tokens와 같다)
- users.device_failed_login_count / device_login_locked_at: '등록 기기' 채널의 로그인 실패·잠금.
  기존 failed_login_count / login_locked_at은 이제 '새 기기' 채널을 뜻한다(컬럼은 그대로, 의미만 좁아졌다).
  기존 행은 둘 다 0/NULL로 시작한다.
- verification_codes.purpose에 NEW_DEVICE (새 기기 로그인 인증)
값 목록은 마이그레이션이 그 시점의 사실을 담아야 하므로 models의 목록을 import하지 않고 그대로 적는다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '9e0f1a2b3c4d'
down_revision: Union[str, Sequence[str], None] = '8d9e0f1a2b3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_PURPOSES = (
    "'SIGNUP_PHONE', 'CHANGE_PHONE', 'PASSWORD_RESET', 'FIND_LOGIN_ID', 'ACCOUNT_PASSWORD_RESET', 'WITHDRAWAL'"
)


def _purpose_check(values: str) -> None:
    op.drop_constraint('ck_verification_codes_purpose', 'verification_codes', type_='check')
    op.create_check_constraint('ck_verification_codes_purpose', 'verification_codes', f"purpose IN ({values})")


def upgrade() -> None:
    op.create_table(
        'user_devices',
        sa.Column('device_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('label', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id']),
        sa.PrimaryKeyConstraint('device_id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index(op.f('ix_user_devices_user_id'), 'user_devices', ['user_id'], unique=False)
    op.add_column('users', sa.Column('device_failed_login_count', sa.SmallInteger(), server_default='0', nullable=False))
    op.add_column('users', sa.Column('device_login_locked_at', sa.DateTime(timezone=True), nullable=True))
    _purpose_check(OLD_PURPOSES + ", 'NEW_DEVICE'")


def downgrade() -> None:
    # 새 기기 인증번호 행은 옛 CHECK를 다시 걸 수 없으니 지운다(10분짜리 일회성 값이다).
    # 되돌리면 등록 기기와 그 채널의 잠금 기록은 사라진다: 모든 로그인이 다시 '새 기기' 카운터 하나로 센다
    op.execute("DELETE FROM verification_codes WHERE purpose = 'NEW_DEVICE'")
    _purpose_check(OLD_PURPOSES)
    op.drop_column('users', 'device_login_locked_at')
    op.drop_column('users', 'device_failed_login_count')
    op.drop_index(op.f('ix_user_devices_user_id'), table_name='user_devices')
    op.drop_table('user_devices')
