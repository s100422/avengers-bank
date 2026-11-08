"""add refresh_tokens.revoked_reason (끊긴 이유: 다른 곳 로그인이면 끊긴 기기에 그 사실을 알려 준다)

Revision ID: 4f2a9c7e1b30
Revises: ccd01fe5b793
Create Date: 2026-11-08 14:00:00

기존 행은 NULL로 둔다(이유를 알 수 없다). 그래서 일관성 CHECK는 "이유가 있으면 폐기된 행"만 강제한다.
값 목록은 마이그레이션이 그 시점의 사실을 담아야 하므로 models.REVOKED_REASONS를 import하지 않고 그대로 적는다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '4f2a9c7e1b30'
down_revision: Union[str, Sequence[str], None] = 'ccd01fe5b793'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('refresh_tokens', sa.Column('revoked_reason', sa.String(length=20), nullable=True))
    op.create_check_constraint(
        'ck_refresh_tokens_revoked_reason',
        'refresh_tokens',
        "revoked_reason IS NULL OR revoked_reason IN "
        "('ROTATED', 'LOGOUT', 'LOGOUT_ALL', 'PASSWORD_CHANGED', 'REUSE_DETECTED', 'LOGIN_ELSEWHERE')",
    )
    op.create_check_constraint(
        'ck_refresh_tokens_reason_is_revoked', 'refresh_tokens', 'revoked_reason IS NULL OR revoked_at IS NOT NULL'
    )


def downgrade() -> None:
    op.drop_constraint('ck_refresh_tokens_reason_is_revoked', 'refresh_tokens', type_='check')
    op.drop_constraint('ck_refresh_tokens_revoked_reason', 'refresh_tokens', type_='check')
    op.drop_column('refresh_tokens', 'revoked_reason')
