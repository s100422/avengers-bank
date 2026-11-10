"""Private in-app feed for committed checking-account movements."""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.accounts.models import AccountNotification, CheckingAccount, CheckingAccountHistory
from avengers_bank.domains.notifications.schemas import NotificationCount, NotificationItem, NotificationReadThrough
from avengers_bank.domains.users.schemas import UserResponse

router = APIRouter(prefix="/notifications", tags=["notifications"], responses=error_responses(401))


@router.get("", response_model=SuccessResponse[list[NotificationItem]])
async def list_notifications(
    user: Annotated[UserResponse, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    async with db.begin():
        rows = (await db.execute(
            select(AccountNotification, CheckingAccountHistory, CheckingAccount)
            .join(CheckingAccountHistory,
                  CheckingAccountHistory.checking_account_history_id == AccountNotification.checking_account_history_id)
            .join(CheckingAccount,
                  CheckingAccount.checking_account_id == CheckingAccountHistory.checking_account_id)
            .where(AccountNotification.user_id == user.user_id, CheckingAccount.user_id == user.user_id)
            .order_by(AccountNotification.notification_id.desc())
            .limit(limit).offset(offset)
        )).all()
    items = [NotificationItem(
        notification_id=n.notification_id, account_id=a.checking_account_id, account_num=a.account_num,
        account_nickname=a.nickname,
        history_id=h.checking_account_history_id, type=h.type, amount=h.amount,
        balance_after=h.balance_after, counterpart_account=h.counterpart_account,
        counterpart_name=h.counterpart_name, date=h.date, read_at=n.read_at,
    ) for n, h, a in rows]
    return SuccessResponse[list[NotificationItem]](data=items)


@router.get("/unread-count", response_model=SuccessResponse[NotificationCount])
async def unread_count(
    user: Annotated[UserResponse, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    async with db.begin():
        count, latest = (await db.execute(select(
            func.count(), func.max(AccountNotification.notification_id)
        ).select_from(AccountNotification).where(
            AccountNotification.user_id == user.user_id,
            AccountNotification.read_at.is_(None),
        ))).one()
    return SuccessResponse[NotificationCount](data=NotificationCount(
        unread_count=count or 0, latest_notification_id=latest,
    ))


@router.post("/read-all", response_model=SuccessResponse[NotificationCount])
async def read_all(
    data: NotificationReadThrough,
    user: Annotated[UserResponse, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    async with db.begin():
        await db.execute(update(AccountNotification).where(
            AccountNotification.user_id == user.user_id,
            AccountNotification.notification_id <= data.through_id,
            AccountNotification.read_at.is_(None),
        ).values(read_at=datetime.now(timezone.utc)))
        remaining, latest = (await db.execute(select(
            func.count(), func.max(AccountNotification.notification_id)
        ).select_from(AccountNotification).where(
            AccountNotification.user_id == user.user_id,
            AccountNotification.read_at.is_(None),
        ))).one()
    return SuccessResponse[NotificationCount](data=NotificationCount(
        unread_count=remaining or 0, latest_notification_id=latest,
    ))
