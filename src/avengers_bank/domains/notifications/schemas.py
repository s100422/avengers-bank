from datetime import datetime

from pydantic import BaseModel, Field


class NotificationItem(BaseModel):
    notification_id: int
    account_id: int
    account_num: str
    account_nickname: str | None
    history_id: int
    type: str
    amount: int
    balance_after: int
    counterpart_account: str | None
    counterpart_name: str | None
    date: datetime
    read_at: datetime | None


class NotificationCount(BaseModel):
    unread_count: int
    latest_notification_id: int | None = None


class NotificationReadThrough(BaseModel):
    through_id: int = Field(gt=0)
