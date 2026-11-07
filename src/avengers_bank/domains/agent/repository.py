from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.agent.models import AgentConversation, AgentMessage, TransferDraft


class AgentRepository:
    async def find_conversation(self, db: AsyncSession, conversation_id: int) -> AgentConversation | None:
        return await db.get(AgentConversation, conversation_id)

    async def find_recent_messages(self, db: AsyncSession, conversation_id: int, limit: int) -> list[AgentMessage]:
        stmt = (
            select(AgentMessage).where(AgentMessage.conversation_id == conversation_id)
            .order_by(AgentMessage.agent_message_id.desc()).limit(limit)
        )
        return list(reversed(list(await db.scalars(stmt))))

    async def save(self, db: AsyncSession, obj):
        db.add(obj)
        await db.flush()
        return obj

    async def find_draft(self, db: AsyncSession, draft_id: str) -> TransferDraft | None:
        return await db.get(TransferDraft, draft_id)

    async def transition_pending(
        self, db: AsyncSession, draft_id: str, user_id: int, to_status: str, now: datetime,
        *, require_unexpired: bool = False,
    ) -> bool:
        """PENDING인 초안 하나만 to_status로 바꾼다. 바뀌었으면 True.

        조건부 UPDATE라서 같은 초안을 동시에 확인·취소해도 한 요청만 성공한다
        (PostgreSQL은 행 잠금 후 조건을 다시 보고, SQLite는 쓰기를 한 줄로 세운다).
        """
        conditions = [
            TransferDraft.draft_id == draft_id, TransferDraft.user_id == user_id, TransferDraft.status == "PENDING"
        ]
        if require_unexpired:
            conditions.append(TransferDraft.expires_at > now)
        values = {"status": to_status, **({"executed_at": now} if to_status == "EXECUTED" else {})}
        result = await db.execute(
            update(TransferDraft).where(*conditions).values(**values).execution_options(synchronize_session=False)
        )
        return result.rowcount == 1


agent_repository = AgentRepository()
