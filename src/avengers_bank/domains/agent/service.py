import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.exceptions import ConflictException, NotFoundException
from avengers_bank.core.timezone import today_kst
from avengers_bank.domains.accounts.kinds import KINDS as ACCOUNT_KINDS
from avengers_bank.domains.accounts.password import check_account_password
from avengers_bank.domains.accounts.service import account_service
from avengers_bank.domains.agent.graph import EMPTY_TEXT, RECURSION_LIMIT, AgentContext, agent_graph
from avengers_bank.domains.agent.model_client import AssistantTurn, ModelClient, ModelReply, Turn, UserTurn
from avengers_bank.domains.agent.models import AgentConversation, AgentMessage, TransferDraft
from avengers_bank.domains.agent.prompts import build_system_prompt
from avengers_bank.domains.agent.repository import agent_repository
from avengers_bank.domains.agent.schemas import (
    AssistantAction,
    ChatRequest,
    Citation,
    ChatResponse,
    DraftCancelResponse,
    DraftConfirmResponse,
    MessageItem,
    ReportSnapshot,
)
from avengers_bank.domains.agent.tools.common import as_utc, mask_num
from avengers_bank.domains.agent.tools.terms import request_sources
from avengers_bank.domains.interbank.schemas import InterbankSend
from avengers_bank.domains.interbank.service import interbank_service
from avengers_bank.domains.terms.search import Passage
from avengers_bank.domains.transfers.schemas import TransferTarget
from avengers_bank.domains.transfers.service import transfer_service
from avengers_bank.domains.users.schemas import UserResponse

logger = logging.getLogger(__name__)

HISTORY_MESSAGES = 10  # 모델에 넘기는 지난 대화 (사용자·AI 메시지 합계)

# 모델이 답변에 붙이는 인용 표시. 사용자에게는 지우고 citations로만 보여 준다
CITATION_MARKER = re.compile(r"\s?\[\[src:([^\]\s]{1,120})\]\]")


class AgentService:
    # ── 채팅 ──────────────────────────────────────────────────────────

    async def chat(self, data: ChatRequest, user: UserResponse, client: ModelClient) -> ChatResponse:
        token = request_sources.set({})  # 이번 요청에서 검색된 약관 출처만 인용·열람할 수 있다
        try:
            return await self._chat(data, user, client)
        finally:
            request_sources.reset(token)

    async def _chat(self, data: ChatRequest, user: UserResponse, client: ModelClient) -> ChatResponse:
        turns: list[Turn] = [*await self._history(data.conversation_id, user), UserTurn(data.message)]
        final = await agent_graph.ainvoke(
            {"system": build_system_prompt(today_kst()), "turns": turns, "tool_log": [], "action": None, "model_calls": 0},
            context=AgentContext(client=client, user=user),
            config={"recursion_limit": RECURSION_LIMIT},
        )
        answer, action = final["answer"], final["action"]
        answer, citations = extract_citations(answer, request_sources.get())
        # 이체나 가입이 필요한 답변은 해당 확인 카드가 우선이다.
        reports = final.get("reports", [])[-4:][::-1] if action is None else []
        saved_card = ReportSnapshot(reports=reports) if reports else action
        conversation_id = await self._save(data, user, answer, final["tool_log"], saved_card, citations)
        return ChatResponse(conversation_id=conversation_id, answer=answer, action=action, citations=citations, reports=reports)

    async def _history(self, conversation_id: int | None, user: UserResponse) -> list[Turn]:
        if conversation_id is None:
            return []
        async with SessionLocal() as db:
            await self._owned_conversation(db, conversation_id, user)
            messages = await agent_repository.find_recent_messages(db, conversation_id, HISTORY_MESSAGES)
        turns = [UserTurn(m.content) if m.role == "user" else AssistantTurn(ModelReply(m.content)) for m in messages]
        while turns and not isinstance(turns[0], UserTurn):  # 대화는 사용자 메시지로 시작해야 한다
            turns.pop(0)
        return turns

    async def _owned_conversation(self, db: AsyncSession, conversation_id: int, user: UserResponse) -> AgentConversation:
        conversation = await agent_repository.find_conversation(db, conversation_id)
        # 남의 대화도 404로 알려서 ID가 있는지 드러나지 않게 한다 (C-031과 같은 방식)
        if conversation is None or conversation.user_id != user.user_id:
            raise NotFoundException(code="CONVERSATION_NOT_FOUND", message="대화를 찾을 수 없습니다.")
        return conversation

    async def _save(
        self, data: ChatRequest, user: UserResponse, answer: str, tool_log: list[dict],
        action: AssistantAction | ReportSnapshot | None,
        citations: list[Citation],
    ) -> int:
        async with SessionLocal() as db, db.begin():
            if data.conversation_id is None:
                conversation = await agent_repository.save(db, AgentConversation(user_id=user.user_id))
            else:
                conversation = await self._owned_conversation(db, data.conversation_id, user)
            cid = conversation.conversation_id
            await agent_repository.save(db, AgentMessage(conversation_id=cid, role="user", content=data.message))
            await agent_repository.save(db, AgentMessage(
                conversation_id=cid, role="assistant", content=answer, tool_calls=tool_log or None,
                action=action.model_dump(mode="json") if action else None,
                citations=[c.model_dump() for c in citations] or None,
            ))
        return cid

    async def list_messages(self, db: AsyncSession, conversation_id: int, user: UserResponse) -> list[MessageItem]:
        await self._owned_conversation(db, conversation_id, user)
        messages = []
        for message in await agent_repository.find_messages(db, conversation_id):
            action = message.action
            reports = []
            if action and action.get("type") == "FINANCIAL_REPORT":
                reports = ReportSnapshot.model_validate(action).reports
                action = None
            messages.append(MessageItem(
                message_id=message.agent_message_id, role=message.role, content=message.content, action=action,
                citations=message.citations or [], created_at=message.created_at, reports=reports,
            ))
        return messages

    # ── 이체 초안 확인·취소 (사용자가 화면에서 직접 누른다. Tool로 등록하지 않는다) ──

    async def confirm_draft(
        self, db: AsyncSession, draft_id: str, account_password: str, user: UserResponse
    ) -> DraftConfirmResponse:
        now = datetime.now(timezone.utc)
        async with db.begin():
            draft = await self._pending_draft(db, draft_id, user)
            expired = as_utc(draft.expires_at) <= now
            if expired:
                await agent_repository.transition_pending(db, draft_id, user.user_id, "EXPIRED", now)
        if expired:
            raise ConflictException(code="DRAFT_EXPIRED", message="이체 확인 시간이 지났습니다. 다시 요청해 주세요.")
        if draft.to_bank:
            return await self._confirm_interbank(db, draft, account_password, user, now)

        # 보내는 계좌 비밀번호는 초안이 아직 PENDING일 때만, 이체 트랜잭션 전에 따로 확인·커밋한다
        # (틀린 횟수가 롤백되지 않게, password.py). 틀려도 초안은 PENDING으로 남아 다시 입력할 수 있다
        await check_account_password(
            db, ACCOUNT_KINDS["checking"], draft.from_checking_account_id, account_password, user
        )
        async with db.begin():
            # PENDING → EXECUTED를 먼저 차지한 요청만 이체한다 (동시 클릭·재시도로 두 번 나가지 않게).
            # 같은 트랜잭션이라 아래 이체가 실패하면(잔액·한도 재검사) 상태도 PENDING으로 되돌아간다.
            if not await agent_repository.transition_pending(
                db, draft_id, user.user_id, "EXECUTED", now, require_unexpired=True
            ):
                raise ConflictException(code="DRAFT_NOT_PENDING", message="이미 처리되었거나 만료된 이체입니다.")
            result = await transfer_service.transfer_in_tx(
                db,
                TransferTarget(
                    from_checking_account_id=draft.from_checking_account_id,
                    to_account_num=draft.to_account_num, amount=draft.amount,
                ),
                user,
            )
        return DraftConfirmResponse(
            draft_id=draft_id, from_account_num_masked=mask_num(result.from_account_num),
            to_account_num_masked=mask_num(result.to_account_num), recipient_name=draft.recipient_name,
            amount=result.amount, balance_after=result.balance_after,
        )

    async def _confirm_interbank(
        self, db: AsyncSession, draft: TransferDraft, account_password: str, user: UserResponse, now: datetime
    ) -> DraftConfirmResponse:
        """타행 초안: 기존 타행 이체 서비스가 비밀번호·잔액·한도 확인, 출금, 허브 송금을 모두 한다 (C-125).

        초안에서 만든 같은 요청 ID를 쓰므로 확인을 두 번 눌러도(동시에·재시도로) 송금은 한 번만 된다.
        허브 결과를 모르면 돈은 출금된 채 PENDING으로 남고, 확인 작업(worker)이 마무리한다.
        """
        result = await interbank_service.send(db, InterbankSend(
            to_bank=draft.to_bank, to_account=draft.to_account_num, from_checking_account_id=draft.from_checking_account_id,
            amount=draft.amount, account_password=account_password,
            request_id=uuid.uuid5(uuid.NAMESPACE_URL, f"agent-transfer-draft:{draft.draft_id}"),
        ), user)
        async with db.begin():
            # 송금이 접수된 뒤라 만료 여부는 보지 않는다(이미 출금됨). 동시 확인으로 먼저 바뀌었어도 같은 송금이다
            await agent_repository.transition_pending(db, draft.draft_id, user.user_id, "EXECUTED", now)
            sender = await account_service.get_owned(db, ACCOUNT_KINDS["checking"], draft.from_checking_account_id, user)
        return DraftConfirmResponse(
            draft_id=draft.draft_id, from_account_num_masked=mask_num(sender.account_num),
            to_account_num_masked=mask_num(result.to_account), recipient_name=result.holder_name or draft.recipient_name,
            amount=result.amount, balance_after=result.balance_after, to_bank_name=result.to_bank_name,
            transfer_status=result.status,
        )

    async def cancel_draft(self, db: AsyncSession, draft_id: str, user: UserResponse) -> DraftCancelResponse:
        now = datetime.now(timezone.utc)
        async with db.begin():
            await self._pending_draft(db, draft_id, user)
            if not await agent_repository.transition_pending(db, draft_id, user.user_id, "CANCELLED", now):
                raise ConflictException(code="DRAFT_NOT_PENDING", message="이미 처리된 이체입니다.")
        return DraftCancelResponse(draft_id=draft_id)

    async def _pending_draft(self, db: AsyncSession, draft_id: str, user: UserResponse) -> TransferDraft:
        draft = await agent_repository.find_draft(db, draft_id)
        if draft is None or draft.user_id != user.user_id:
            raise NotFoundException(code="DRAFT_NOT_FOUND", message="이체 초안을 찾을 수 없습니다.")
        if draft.status != "PENDING":
            raise ConflictException(code="DRAFT_NOT_PENDING", message="이미 처리되었거나 만료된 이체입니다.")
        return draft


def extract_citations(answer: str, sources: dict[str, Passage] | None) -> tuple[str, list[Citation]]:
    """답변의 [[src:id]] 표시를 모두 지우고, 이번 요청에서 실제로 검색된 id만 인용으로 남긴다 (처음 나온 순서).
    모르는 id(지어낸 것·원문 속 주입 문구)는 버리고, 검색됐지만 인용하지 않은 출처는 보여 주지 않는다."""
    sources = sources or {}
    citations: dict[str, Citation] = {}
    for sid in CITATION_MARKER.findall(answer):
        p = sources.get(sid)
        if p is not None and sid not in citations:
            citations[sid] = Citation(
                source_id=sid, document_version_id=p.terms_version_id, title=p.title, version=p.version,
                section_id=p.section_id, section_title=p.section_title, url=p.url,
            )
    text = CITATION_MARKER.sub("", answer).strip()
    return text or EMPTY_TEXT, list(citations.values())


agent_service = AgentService()
