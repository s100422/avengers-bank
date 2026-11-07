from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.timezone import KST
from avengers_bank.domains.products.service import product_service


class ToolArgs(BaseModel):
    # user_id처럼 정의하지 않은 인자는 거절한다. 사용자는 항상 서버의 인증 정보에서 온다
    model_config = ConfigDict(extra="forbid")


def mask_num(num: str | None) -> str | None:
    """계좌·카드번호에서 첫 묶음과 마지막 4자리만 남긴다. 110-123-456789 → 110-***-**6789"""
    if not num:
        return num
    head, sep, rest = num.partition("-")
    if not sep:
        head, rest = "", num
    keep, out = 4, []
    for ch in reversed(rest):
        if ch.isdigit():
            out.append(ch if keep > 0 else "*")
            keep -= 1
        else:
            out.append(ch)
    return head + sep + "".join(reversed(out))


def as_utc(moment: datetime) -> datetime:
    """SQLite는 시간대 없이 돌려줘서 UTC로 본다."""
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def to_kst(moment: datetime) -> datetime:
    return as_utc(moment).astimezone(KST)


async def account_name(db: AsyncSession, account, cache: dict[int, str] | None = None) -> str:
    """별칭이 있으면 별칭, 없으면 상품 이름."""
    if account.nickname:
        return account.nickname
    cache = {} if cache is None else cache
    if account.product_id not in cache:
        cache[account.product_id] = (await product_service.get_account_product(db, account.product_id)).name
    return cache[account.product_id]
