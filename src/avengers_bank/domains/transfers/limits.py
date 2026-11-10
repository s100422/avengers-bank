"""Shared withdrawal limits for in-bank and interbank transfers.

Call only after locking the sender's checking account row.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.exceptions import BadRequestException
from avengers_bank.core.timezone import today_start_utc
from avengers_bank.domains.accounts.models import CheckingAccount
from avengers_bank.domains.accounts.repository import account_repository


async def check_transfer_limits(db: AsyncSession, sender: CheckingAccount, amount: int) -> None:
    if sender.balance < amount:
        raise BadRequestException(code="INSUFFICIENT_BALANCE", message="잔액이 부족합니다.")
    if amount > sender.per_transfer_limit:
        raise BadRequestException(code="PER_TRANSFER_LIMIT_EXCEEDED",
                                  message=f"1회 이체 한도({sender.per_transfer_limit:,}원)를 초과했습니다.")
    used_today = await account_repository.sum_today_transfer_amount(
        db, sender.checking_account_id, today_start_utc())
    if used_today + amount > sender.daily_transfer_limit:
        raise BadRequestException(code="DAILY_LIMIT_EXCEEDED",
                                  message=f"1일 이체 한도({sender.daily_transfer_limit:,}원)를 초과했습니다. 오늘 이미 {used_today:,}원을 보냈습니다.")
