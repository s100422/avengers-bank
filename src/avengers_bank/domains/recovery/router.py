from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, BeforeValidator, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.accounts.schemas import AccountPassword
from avengers_bank.domains.recovery import service
from avengers_bank.domains.users.validators import NewPassword, normalize_login_id, strip

router = APIRouter(prefix="/recovery", tags=["recovery (아이디·비밀번호 찾기)"], responses=error_responses(422))

START_MESSAGE = "입력하신 정보가 맞으면 등록된 휴대폰으로 인증번호를 보냈습니다."


class StartRequest(BaseModel):
    purpose: Literal["PASSWORD_RESET", "FIND_LOGIN_ID"]
    # PASSWORD_RESET이면 필수, FIND_LOGIN_ID면 보내지 않는다(보내도 무시). 형식 검사는 하지 않는다(로그인과 같은 이유)
    login_id: Annotated[Annotated[str, Field(min_length=1, max_length=50)] | None, BeforeValidator(normalize_login_id)] = None
    account_num: Annotated[Annotated[str, Field(min_length=1, max_length=20)], BeforeValidator(strip)]  # 입출금 계좌번호
    account_password: AccountPassword  # 그 계좌의 비밀번호 (형식 검사 없음: 틀린 값은 실패 횟수로 센다)

    @model_validator(mode="after")
    def _login_id_for_reset(self):
        if self.purpose == "PASSWORD_RESET" and self.login_id is None:
            raise ValueError("아이디를 입력해 주세요.")
        return self


class StartResponse(BaseModel):
    recovery_token: str = Field(repr=False)  # 10분. 정보가 틀렸어도 같은 모양으로 온다
    expires_in: int


class VerifyRequest(BaseModel):
    recovery_token: str = Field(min_length=1, max_length=2048, repr=False)
    code: str = Field(min_length=1, max_length=10)  # 형식이 틀려도 422가 아니라 '틀린 시도'로 센다 (/verification과 같게)


class FoundLoginId(BaseModel):
    masked_login_id: str  # 앞 2자 + 마지막 1자. 전체 아이디는 등록 휴대폰으로 문자가 간다


class ResetToken(BaseModel):
    reset_token: str = Field(repr=False)  # 10분, 1회용. POST /recovery/password에 넣는다
    expires_in: int


class PasswordResetRequest(BaseModel):
    reset_token: str = Field(min_length=1, max_length=2048, repr=False)
    new_password: NewPassword  # 가입과 같은 규칙


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.post("/start", response_model=SuccessResponse[StartResponse], responses=error_responses(429))
async def start(data: StartRequest, request: Request, response: Response, db: Annotated[AsyncSession, Depends(get_db)]):
    """언제나 같은 응답: 계좌·아이디가 있는지, 계좌 비밀번호가 맞는지 드러내지 않는다. 429는 IP 한도(15분 10번)뿐."""
    token = await service.start(
        db, purpose=data.purpose, login_id=data.login_id if data.purpose == "PASSWORD_RESET" else None,
        account_num=data.account_num, account_password=data.account_password,
        ip=request.client.host if request.client else "unknown",
    )
    _no_store(response)
    return SuccessResponse[StartResponse](
        data=StartResponse(recovery_token=token, expires_in=service.EXPIRES_IN), message=START_MESSAGE
    )


@router.post("/verify", response_model=SuccessResponse[FoundLoginId | ResetToken], responses=error_responses(400))
async def verify(data: VerifyRequest, response: Response, db: Annotated[AsyncSession, Depends(get_db)]):
    """FIND_LOGIN_ID: {masked_login_id} (전체 아이디는 문자로). PASSWORD_RESET: {reset_token, expires_in}."""
    result = await service.verify(db, data.recovery_token, data.code)
    _no_store(response)
    return SuccessResponse[FoundLoginId | ResetToken](data=result, message="인증되었습니다.")


@router.post("/password", response_model=SuccessResponse[None], responses=error_responses(400))
async def reset_password(data: PasswordResetRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    """새 비밀번호 + 로그인 잠금 해제 + 모든 기기 로그아웃 + 알림 문자. 자동 로그인은 하지 않는다."""
    await service.reset_password(db, data.reset_token, data.new_password)
    return SuccessResponse[None](data=None, message="비밀번호를 재설정했습니다. 새 비밀번호로 로그인해 주세요.")
