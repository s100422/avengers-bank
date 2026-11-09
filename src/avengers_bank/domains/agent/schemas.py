from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from avengers_bank.domains.accounts.schemas import AccountPassword


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    conversation_id: int | None = None


class TransferAction(BaseModel):
    type: Literal["TRANSFER_CONFIRMATION"] = "TRANSFER_CONFIRMATION"
    draft_id: str
    # 보내는 입출금 계좌 id (비밀번호 미설정·잠김 안내 링크를 그 계좌 상세로 보낸다). 새 초안은 항상 채운다.
    # None 허용: 이 필드가 생기기 전에 저장된 대화 기록(agent_messages.action)을 다시 읽을 때 검증이 깨지지 않게
    from_account_id: int | None = None
    from_account_name: str
    from_account_num_masked: str
    recipient_name: str
    to_account_num_masked: str
    amount: int
    expected_balance_after: int
    expires_at: datetime


class SummaryRow(BaseModel):
    label: str
    value: str


class OpenAccountAction(BaseModel):
    """예·적금 가입 화면을 미리 채워 여는 카드 (C-103). 가입은 하지 않는다. 약관 동의와 계좌 비밀번호는 가입 화면에서 직접 한다."""

    type: Literal["OPEN_ACCOUNT"] = "OPEN_ACCOUNT"
    kind: Literal["deposit", "savings"]
    product_id: int
    product_name: str
    interest_rate: str  # 연 %, 예: "3.5"
    summary: list[SummaryRow]  # 카드에 보여 줄 값 (표시용 글)
    fields: dict[str, str]  # 가입 화면 입력칸 이름 → 값 (initial_amount, maturity_date, checking_account_id ...)


# type 값으로 구분한다. 예전에 저장된 대화 기록(type=TRANSFER_CONFIRMATION)도 그대로 읽힌다
AssistantAction = Annotated[TransferAction | OpenAccountAction, Field(discriminator="type")]


class Citation(BaseModel):
    """서버가 이번 요청의 검색 결과로 확인한 약관 출처 (C-075)."""

    source_id: str
    document_version_id: int  # terms_version_id
    title: str
    version: str
    section_id: str
    section_title: str
    url: str  # /terms/{document_version_id}#{section_id}


class ChatResponse(BaseModel):
    conversation_id: int
    answer: str
    action: AssistantAction | None = None
    citations: list[Citation] = []


class MessageItem(BaseModel):
    message_id: int
    role: Literal["user", "assistant"]
    content: str
    action: AssistantAction | None = None
    citations: list[Citation] = []
    created_at: datetime


class DraftConfirmRequest(BaseModel):
    """확인 카드에서 사용자가 직접 입력한다. 대화(LLM)로는 절대 받지 않는다 (대화·로그에 남지 않게)."""

    account_password: AccountPassword  # 보내는 입출금 계좌의 비밀번호


class DraftConfirmResponse(BaseModel):
    draft_id: str
    status: Literal["EXECUTED"] = "EXECUTED"
    from_account_num_masked: str
    to_account_num_masked: str
    recipient_name: str
    amount: int
    balance_after: int


class DraftCancelResponse(BaseModel):
    draft_id: str
    status: Literal["CANCELLED"] = "CANCELLED"
