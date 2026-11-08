"""AI 금융 비서 대화·이체 초안 (C-070).

Tool의 원본 결과는 저장하지 않는다. 메시지에는 답변 글, 호출한 Tool 이름과 성공 여부, 이체 확인 action만 남긴다.
"""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class AgentConversation(Base):
    __tablename__ = "agent_conversations"

    conversation_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (
        Index("ix_agent_messages_conversation", "conversation_id", "agent_message_id"),
        CheckConstraint("role IN ('user', 'assistant')", name="ck_agent_messages_role"),
    )

    agent_message_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversations.conversation_id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # [{"name": "get_my_accounts", "ok": true}, ...] — 결과 값은 남기지 않는다
    tool_calls: Mapped[list | None] = mapped_column(JSON)
    action: Mapped[dict | None] = mapped_column(JSON)  # 이체 확인 action (마스킹된 값만)
    citations: Mapped[list | None] = mapped_column(JSON)  # 서버가 검증한 약관 출처 (C-075)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


DRAFT_STATUSES = ("PENDING", "EXECUTED", "EXPIRED", "CANCELLED")


class TransferDraft(Base):
    """AI가 만든 이체 초안. 사용자가 화면에서 확인해야만 실행된다."""

    __tablename__ = "agent_transfer_drafts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'EXECUTED', 'EXPIRED', 'CANCELLED')", name="ck_agent_transfer_drafts_status"
        ),
        CheckConstraint("amount > 0", name="ck_agent_transfer_drafts_amount_positive"),
    )

    draft_id: Mapped[str] = mapped_column(String(43), primary_key=True)  # 추측할 수 없는 임의 문자열
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False, index=True)
    from_checking_account_id: Mapped[int] = mapped_column(
        ForeignKey("checking_accounts.checking_account_id"), nullable=False
    )
    to_account_num: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient_name: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="PENDING", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
