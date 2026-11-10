"""Link new transfer history to request/clearing IDs without guessing old rows.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, Sequence[str], None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_refresh_tokens_revoked_reason", "refresh_tokens", type_="check")
    op.create_check_constraint("ck_refresh_tokens_revoked_reason", "refresh_tokens",
                               "revoked_reason IS NULL OR revoked_reason IN ('ROTATED', 'LOGOUT', 'LOGOUT_ALL', 'PASSWORD_CHANGED', 'PHONE_CHANGED', 'REUSE_DETECTED', 'LOGIN_ELSEWHERE', 'WITHDRAWN')")
    op.drop_constraint("ck_verification_codes_purpose", "verification_codes", type_="check")
    op.create_check_constraint("ck_verification_codes_purpose", "verification_codes",
                               "purpose IN ('SIGNUP_PHONE', 'CHANGE_PHONE', 'CHANGE_PHONE_OLD', 'CHANGE_PHONE_NEW', 'PASSWORD_RESET', 'FIND_LOGIN_ID', 'ACCOUNT_PASSWORD_RESET', 'WITHDRAWAL', 'NEW_DEVICE')")
    op.add_column("checking_account_histories", sa.Column("transfer_id", sa.String(36), nullable=True))
    op.add_column("checking_account_histories", sa.Column("request_id", sa.String(36), nullable=True))
    op.create_index("ix_checking_account_histories_transfer_id", "checking_account_histories", ["transfer_id"])
    op.create_unique_constraint("uq_checking_account_histories_request_id", "checking_account_histories", ["request_id"])


def downgrade() -> None:
    op.drop_constraint("ck_refresh_tokens_revoked_reason", "refresh_tokens", type_="check")
    op.create_check_constraint("ck_refresh_tokens_revoked_reason", "refresh_tokens",
                               "revoked_reason IS NULL OR revoked_reason IN ('ROTATED', 'LOGOUT', 'LOGOUT_ALL', 'PASSWORD_CHANGED', 'REUSE_DETECTED', 'LOGIN_ELSEWHERE', 'WITHDRAWN')")
    op.drop_constraint("ck_verification_codes_purpose", "verification_codes", type_="check")
    op.create_check_constraint("ck_verification_codes_purpose", "verification_codes",
                               "purpose IN ('SIGNUP_PHONE', 'CHANGE_PHONE', 'PASSWORD_RESET', 'FIND_LOGIN_ID', 'ACCOUNT_PASSWORD_RESET', 'WITHDRAWAL', 'NEW_DEVICE')")
    op.drop_constraint("uq_checking_account_histories_request_id", "checking_account_histories", type_="unique")
    op.drop_index("ix_checking_account_histories_transfer_id", table_name="checking_account_histories")
    op.drop_column("checking_account_histories", "request_id")
    op.drop_column("checking_account_histories", "transfer_id")
