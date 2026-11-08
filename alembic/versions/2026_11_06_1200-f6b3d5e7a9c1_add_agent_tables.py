"""add AI agent conversations, messages and transfer drafts (C-070)

Revision ID: f6b3d5e7a9c1
Revises: e5a2c4d6f8b0
Create Date: 2026-11-06 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f6b3d5e7a9c1'
down_revision: Union[str, Sequence[str], None] = 'e5a2c4d6f8b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agent_conversations',
        sa.Column('conversation_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id']),
        sa.PrimaryKeyConstraint('conversation_id'),
    )
    op.create_index('ix_agent_conversations_user_id', 'agent_conversations', ['user_id'])

    op.create_table(
        'agent_messages',
        sa.Column('agent_message_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('conversation_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=10), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('tool_calls', sa.JSON(), nullable=True),
        sa.Column('action', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name='ck_agent_messages_role'),
        sa.ForeignKeyConstraint(['conversation_id'], ['agent_conversations.conversation_id']),
        sa.PrimaryKeyConstraint('agent_message_id'),
    )
    op.create_index('ix_agent_messages_conversation', 'agent_messages', ['conversation_id', 'agent_message_id'])

    op.create_table(
        'agent_transfer_drafts',
        sa.Column('draft_id', sa.String(length=43), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('from_checking_account_id', sa.Integer(), nullable=False),
        sa.Column('to_account_num', sa.String(length=20), nullable=False),
        sa.Column('recipient_name', sa.String(length=50), nullable=False),
        sa.Column('amount', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'EXECUTED', 'EXPIRED', 'CANCELLED')", name='ck_agent_transfer_drafts_status'
        ),
        sa.CheckConstraint('amount > 0', name='ck_agent_transfer_drafts_amount_positive'),
        sa.ForeignKeyConstraint(['from_checking_account_id'], ['checking_accounts.checking_account_id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id']),
        sa.PrimaryKeyConstraint('draft_id'),
    )
    op.create_index('ix_agent_transfer_drafts_user_id', 'agent_transfer_drafts', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_agent_transfer_drafts_user_id', table_name='agent_transfer_drafts')
    op.drop_table('agent_transfer_drafts')
    op.drop_index('ix_agent_messages_conversation', table_name='agent_messages')
    op.drop_table('agent_messages')
    op.drop_index('ix_agent_conversations_user_id', table_name='agent_conversations')
    op.drop_table('agent_conversations')
