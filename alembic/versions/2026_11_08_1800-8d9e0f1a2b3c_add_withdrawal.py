"""add withdrawal: users.deleted_at, checking_accounts.closed_at, purpose WITHDRAWAL, revoked_reason WITHDRAWN

Revision ID: 8d9e0f1a2b3c
Revises: 6b7c8d9e0f1a
Create Date: 2026-11-08 18:00:00

회원 탈퇴(소프트 삭제). 기존 행은 모두 NULL(탈퇴 안 함·열린 계좌)로 시작한다.
- users.deleted_at: 탈퇴 시각. 행은 남겨 login_id 재가입을 막고 거래 기록이 가리킬 수 있게 한다
- checking_accounts.closed_at: 탈퇴로 닫힌 입출금 계좌. 남이 이 계좌로 이체하면 "받는 계좌를 찾을 수 없습니다"
- verification_codes.purpose에 WITHDRAWAL (탈퇴 본인 확인), refresh_tokens.revoked_reason에 WITHDRAWN
값 목록은 마이그레이션이 그 시점의 사실을 담아야 하므로 models의 목록을 import하지 않고 그대로 적는다.
users.phone은 NOT NULL을 그대로 둔다: 탈퇴하면 빈 문자열로 가린다(users/withdrawal.py 참고).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '8d9e0f1a2b3c'
down_revision: Union[str, Sequence[str], None] = '6b7c8d9e0f1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_PURPOSES = "'SIGNUP_PHONE', 'CHANGE_PHONE', 'PASSWORD_RESET', 'FIND_LOGIN_ID', 'ACCOUNT_PASSWORD_RESET'"
OLD_REASONS = "'ROTATED', 'LOGOUT', 'LOGOUT_ALL', 'PASSWORD_CHANGED', 'REUSE_DETECTED', 'LOGIN_ELSEWHERE'"


def _purpose_check(values: str) -> None:
    op.drop_constraint('ck_verification_codes_purpose', 'verification_codes', type_='check')
    op.create_check_constraint('ck_verification_codes_purpose', 'verification_codes', f"purpose IN ({values})")


def _reason_check(values: str) -> None:
    op.drop_constraint('ck_refresh_tokens_revoked_reason', 'refresh_tokens', type_='check')
    op.create_check_constraint(
        'ck_refresh_tokens_revoked_reason', 'refresh_tokens', f"revoked_reason IS NULL OR revoked_reason IN ({values})"
    )


def upgrade() -> None:
    op.add_column('users', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('checking_accounts', sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True))
    _purpose_check(OLD_PURPOSES + ", 'WITHDRAWAL'")
    _reason_check(OLD_REASONS + ", 'WITHDRAWN'")


def downgrade() -> None:
    # 새 값을 쓰는 행이 있으면 옛 CHECK를 다시 걸 수 없다. 탈퇴 인증번호 행은 지우고(탈퇴하면 어차피 지운다),
    # 탈퇴로 끊긴 세션은 이유를 LOGOUT_ALL(모든 세션 끊기)로 바꾼다. 탈퇴 사실(deleted_at)·닫힌 계좌 표시는
    # 컬럼과 함께 사라진다 — 되돌린 뒤 탈퇴 회원은 가려진 정보·맞지 않는 비밀번호만 남은 계정이 된다
    op.execute("DELETE FROM verification_codes WHERE purpose = 'WITHDRAWAL'")
    op.execute("UPDATE refresh_tokens SET revoked_reason = 'LOGOUT_ALL' WHERE revoked_reason = 'WITHDRAWN'")
    _reason_check(OLD_REASONS)
    _purpose_check(OLD_PURPOSES)
    op.drop_column('checking_accounts', 'closed_at')
    op.drop_column('users', 'deleted_at')
