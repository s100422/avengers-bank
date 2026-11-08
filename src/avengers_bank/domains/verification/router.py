from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.users.schemas import UserResponse
from avengers_bank.domains.users.validators import Phone
from avengers_bank.domains.verification.service import CODE_TTL, start_verification, verify_code

router = APIRouter(prefix="/verification", tags=["verification"], responses=error_responses(422))


class SendRequest(BaseModel):
    phone: Phone
    purpose: Literal["SIGNUP_PHONE"]  # 로그인 없이 받을 수 있는 인증. 2단계: PASSWORD_RESET, FIND_LOGIN_ID


class SendForMeRequest(BaseModel):
    # CHANGE_PHONE: 바꿀 새 번호(필수). ACCOUNT_PASSWORD_RESET: 보내지 않아도 되고, 보내도 무시하고 등록된 번호로 보낸다
    phone: Phone | None = None
    purpose: Literal["CHANGE_PHONE", "ACCOUNT_PASSWORD_RESET"]

    @model_validator(mode="after")
    def _phone_for_change(self):
        if self.purpose == "CHANGE_PHONE" and self.phone is None:
            raise ValueError("바꿀 휴대폰 번호를 입력해 주세요.")
        return self


class SendResponse(BaseModel):
    verification_id: int
    expires_in: int  # 인증번호 유효 시간(초)


class VerifyRequest(BaseModel):
    verification_id: int
    code: str = Field(min_length=1, max_length=10)  # 형식이 틀려도 422가 아니라 '틀린 시도'로 센다


class VerifyResponse(BaseModel):
    verification_token: str = Field(repr=False)  # 10분, 1회용. 가입·번호 변경 요청에 그대로 넣는다


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/phone/send", response_model=SuccessResponse[SendResponse], responses=error_responses(429))
async def send(data: SendRequest, request: Request, db: Annotated[AsyncSession, Depends(get_db)]):
    # 이미 가입된 번호인지 알려 주지 않는다: 번호만으로 회원 여부를 알아낼 수 없게 언제나 같은 응답
    verification_id = await start_verification(db, purpose=data.purpose, phone=data.phone, ip=_ip(request))
    return SuccessResponse[SendResponse](
        data=SendResponse(verification_id=verification_id, expires_in=int(CODE_TTL.total_seconds())),
        message="인증번호를 보냈습니다.",
    )


@router.post("/phone/send-for-me", response_model=SuccessResponse[SendResponse], responses=error_responses(401, 429))
async def send_for_me(
    data: SendForMeRequest,
    request: Request,
    current_user: Annotated[UserResponse, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # CHANGE_PHONE: 바꿀 새 번호로 보낸다. ACCOUNT_PASSWORD_RESET: 등록된 번호로만 보낸다(본문 phone 무시) —
    # 훔친 세션으로 남의 번호를 넣어 계좌 비밀번호를 바꾸지 못하게
    phone = current_user.phone if data.purpose == "ACCOUNT_PASSWORD_RESET" else data.phone
    verification_id = await start_verification(
        db, purpose=data.purpose, phone=phone, user_id=current_user.user_id, ip=_ip(request)
    )
    return SuccessResponse[SendResponse](
        data=SendResponse(verification_id=verification_id, expires_in=int(CODE_TTL.total_seconds())),
        message="인증번호를 보냈습니다.",
    )


@router.post("/phone/verify", response_model=SuccessResponse[VerifyResponse], responses=error_responses(400))
async def verify(data: VerifyRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    token = await verify_code(db, data.verification_id, data.code)
    return SuccessResponse[VerifyResponse](data=VerifyResponse(verification_token=token), message="인증되었습니다.")
