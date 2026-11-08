from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    conversation_id: int | None = None


class TransferAction(BaseModel):
    type: Literal["TRANSFER_CONFIRMATION"] = "TRANSFER_CONFIRMATION"
    draft_id: str
    from_account_name: str
    from_account_num_masked: str
    recipient_name: str
    to_account_num_masked: str
    amount: int
    expected_balance_after: int
    expires_at: datetime


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
    action: TransferAction | None = None
    citations: list[Citation] = []


class MessageItem(BaseModel):
    message_id: int
    role: Literal["user", "assistant"]
    content: str
    action: TransferAction | None = None
    citations: list[Citation] = []
    created_at: datetime


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
