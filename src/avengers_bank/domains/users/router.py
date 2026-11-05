from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.exceptions import BadRequestException, UnauthorizedException
from avengers_bank.core.login_limiter import login_limiter
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.users.schemas import (
    PasswordChange,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
)
from avengers_bank.domains.users.service import user_service

router = APIRouter(prefix="/users", tags=["users"], responses=error_responses(422))


@router.post(
    "/signup",
    response_model=SuccessResponse[UserResponse],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(409),
)
async def signup(data: UserCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    user = await user_service.signup(db, data)
    return SuccessResponse[UserResponse](data=user, message="회원가입이 완료되었습니다.")


@router.post(
    "/login",
    response_model=SuccessResponse[TokenResponse],
    responses=error_responses(401, 429),
)
async def login(
    data: UserLogin, db: Annotated[AsyncSession, Depends(get_db)], response: Response, request: Request
):
    ip = request.client.host if request.client else "unknown"
    login_limiter.check(data.login_id, ip)  # 한도를 넘었으면 비밀번호 검증 전에 429
    try:
        access_token = await user_service.login(db, data)
    except UnauthorizedException:
        login_limiter.record_failure(data.login_id, ip)
        raise
    login_limiter.reset(data.login_id, ip)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return SuccessResponse[TokenResponse](data=TokenResponse(access_token=access_token))


@router.get(
    "/me", response_model=SuccessResponse[UserResponse], responses=error_responses(401)
)
async def get_me(current_user: Annotated[UserResponse, Depends(get_current_user)]):
    return SuccessResponse[UserResponse](data=current_user)


@router.patch(
    "/me/password",
    response_model=SuccessResponse[None],
    responses=error_responses(400, 401, 429),
)
async def change_password(
    data: PasswordChange,
    current_user: Annotated[UserResponse, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
):
    # 로그인과 같은 실패 한도를 쓴다. 훔친 토큰으로 현재 비밀번호를 알아내려는 시도를 막는다 (C-045)
    ip = request.client.host if request.client else "unknown"
    login_limiter.check(current_user.login_id, ip)
    try:
        await user_service.change_password(db, current_user, data)
    except BadRequestException as error:
        if error.code == "INVALID_CURRENT_PASSWORD":
            login_limiter.record_failure(current_user.login_id, ip)
        raise
    login_limiter.reset(current_user.login_id, ip)
    return SuccessResponse[None](data=None, message="비밀번호가 변경되었습니다.")


@router.patch(
    "/me", response_model=SuccessResponse[UserResponse], responses=error_responses(401)
)
async def update_me(
    data: UserUpdate,
    current_user: Annotated[UserResponse, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await user_service.update_me(db, current_user, data)
    return SuccessResponse[UserResponse](data=user, message="내 정보가 수정되었습니다.")
