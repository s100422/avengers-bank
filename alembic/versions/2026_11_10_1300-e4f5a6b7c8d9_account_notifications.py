"""Store in-app notices for committed checking-account movements.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, Sequence[str], None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account_notifications",
        sa.Column("notification_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("checking_account_history_id", sa.Integer(),
                  sa.ForeignKey("checking_account_histories.checking_account_history_id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("checking_account_history_id", name="uq_account_notifications_history"),
    )
    op.create_index("ix_account_notifications_user_created", "account_notifications", ["user_id", "created_at"])
    op.create_index("ix_account_notifications_user_read", "account_notifications", ["user_id", "read_at"])


def downgrade() -> None:
    op.drop_index("ix_account_notifications_user_read", table_name="account_notifications")
    op.drop_index("ix_account_notifications_user_created", table_name="account_notifications")
    op.drop_table("account_notifications")
