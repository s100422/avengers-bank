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


class ChatResponse(BaseModel):
    conversation_id: int
    answer: str
    action: TransferAction | None = None


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
