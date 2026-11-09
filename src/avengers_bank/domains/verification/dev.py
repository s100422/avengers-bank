"""개발용 API: 문자함 읽기, 로그인 잠금 해제.

ENABLE_DEV_ENDPOINTS=true 일 때만 main.py가 등록한다. 운영 환경에서는 절대 열리지 않는다
(문자함이 열리면 남의 인증번호를 읽을 수 있고, 잠금 해제가 열리면 비밀번호 대입을 무한히 할 수 있다).
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.exceptions import NotFoundException
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.users.service import user_service
from avengers_bank.domains.users.validators import Phone
from avengers_bank.domains.verification.sms import dev_messages

router = APIRouter(prefix="/dev", tags=["dev (개발용)"], responses=error_responses(422))


class SmsMessage(BaseModel):
    text: str
    sent_at: datetime


@router.get("/sms", response_model=SuccessResponse[list[SmsMessage]])
async def read_sms(phone: Phone):
    """그 번호로 보낸 최근 문자 (최신순, 최대 20). 개발용 발송기(SMS_SENDER=dev)가 메모리에 쌓은 것이다."""
    return SuccessResponse[list[SmsMessage]](data=[SmsMessage(text=t, sent_at=at) for t, at in dev_messages(phone)])


@router.post("/users/{login_id}/unlock", response_model=SuccessResponse[None], responses=error_responses(404))
async def unlock(login_id: str, db: Annotated[AsyncSession, Depends(get_db)]):
    if not await user_service.unlock_login(db, login_id.strip().lower()):
        raise NotFoundException("사용자를 찾을 수 없습니다.", code="USER_NOT_FOUND")
    return SuccessResponse[None](data=None, message="로그인 잠금을 해제했습니다.")
