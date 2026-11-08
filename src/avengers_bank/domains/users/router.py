from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.login_limiter import login_limiter
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.users.schemas import (
    LogoutRequest,
    PasswordChange,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
)
from avengers_bank.domains.users.service import user_service

router = APIRouter(prefix="/users", tags=["users"], responses=error_responses(422))


def _no_store(response: Response) -> None:
    # 토큰이 담긴 응답을 브라우저·프록시가 저장하지 않게 한다
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.post(
    "/signup",
    response_model=SuccessResponse[UserResponse],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 409),
)
async def signup(data: UserCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    user = await user_service.signup(db, data)
    return SuccessResponse[UserResponse](data=user, message="회원가입이 완료되었습니다.")


@router.post(
    "/login",
    response_model=SuccessResponse[TokenResponse],
    responses=error_responses(401, 403, 429),
)
async def login(
    data: UserLogin, db: Annotated[AsyncSession, Depends(get_db)], response: Response, request: Request
):
    ip = request.client.host if request.client else "unknown"
    # IP 한도(여러 아이디를 찔러 보는 공격): 검증 전에 시도를 먼저 센다(넘었으면 429). 틀리면 그 기록이 그대로 실패 1회.
    # 같은 아이디를 계속 틀리는 것은 user_service.login의 DB 잠금(5회 연속)이 막는다
    attempt = login_limiter.acquire(ip)
    tokens = await user_service.login(db, data)
    login_limiter.reset(ip, attempt)
    _no_store(response)
    return SuccessResponse[TokenResponse](data=tokens)


@router.post(
    "/token/refresh",
    response_model=SuccessResponse[TokenResponse],
    responses=error_responses(401),
)
async def refresh_token(data: RefreshRequest, db: Annotated[AsyncSession, Depends(get_db)], response: Response):
    # 액세스 토큰을 요구하지 않는다: 액세스 토큰이 만료됐을 때 부르는 API이기 때문이다
    tokens = await user_service.refresh(db, data.refresh_token)
    _no_store(response)
    return SuccessResponse[TokenResponse](data=tokens)


@router.post("/logout", response_model=SuccessResponse[None])
async def logout(data: LogoutRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    # 액세스 토큰이 만료된 상태에서도 로그아웃할 수 있어야 하므로 갱신 토큰만 받는다
    await user_service.logout(db, data.refresh_token)
    return SuccessResponse[None](data=None, message="로그아웃되었습니다.")


@router.post("/logout-all", response_model=SuccessResponse[None], responses=error_responses(401))
async def logout_all(
    current_user: Annotated[UserResponse, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # 위 /logout과 달리 액세스 토큰으로 본인임을 확인한다: 남의 모든 세션을 끊는 데 쓰이면 안 되므로
    await user_service.logout_all(db, current_user)
    return SuccessResponse[None](data=None, message="모든 기기에서 로그아웃되었습니다.")


@router.get(
    "/me", response_model=SuccessResponse[UserResponse], responses=error_responses(401)
)
async def get_me(current_user: Annotated[UserResponse, Depends(get_current_user)]):
    return SuccessResponse[UserResponse](data=current_user)


@router.patch(
    "/me/password",
    response_model=SuccessResponse[TokenResponse],
    responses=error_responses(400, 401, 403),
)
async def change_password(
    data: PasswordChange,
    current_user: Annotated[UserResponse, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
):
    # 현재 비밀번호 틀림은 로그인 실패와 같은 DB 카운터로 센다(5회면 로그인 잠금). 훔친 토큰으로 현재 비밀번호를
    # 알아내려는 시도를 막는다 (C-045 → C-090)
    tokens = await user_service.change_password(db, current_user, data)
    _no_store(response)
    return SuccessResponse[TokenResponse](data=tokens, message="비밀번호가 변경되었습니다.")


@router.patch(
    "/me", response_model=SuccessResponse[UserResponse], responses=error_responses(400, 401)
)
async def update_me(
    data: UserUpdate,
    current_user: Annotated[UserResponse, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await user_service.update_me(db, current_user, data)
    return SuccessResponse[UserResponse](data=user, message="내 정보가 수정되었습니다.")
