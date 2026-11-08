from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.cookies import (
    DEVICE_COOKIE,
    REFRESH_COOKIE,
    clear_cookie,
    clear_cookie_header,
    require_allowed_origin,
    set_device_cookie,
    set_refresh_cookie,
)
from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.exceptions import UnauthorizedException
from avengers_bank.core.login_limiter import login_limiter
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.users.schemas import (
    DeviceChallenge,
    DeviceChallengeSend,
    DeviceLogin,
    DeviceResponse,
    LoginOk,
    PasswordChange,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
    WithdrawalRequest,
    WithdrawalStatus,
)
from avengers_bank.domains.users import withdrawal
from avengers_bank.domains.users.service import Session, user_service
from avengers_bank.domains.verification.router import SendResponse
from avengers_bank.domains.verification.service import CODE_TTL

router = APIRouter(prefix="/users", tags=["users"], responses=error_responses(422))


def _no_store(response: Response) -> None:
    # 토큰이 담긴 응답을 브라우저·프록시가 저장하지 않게 한다
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _login_ok(session: Session, response: Response) -> LoginOk:
    """갱신 토큰(과 새로 등록한 기기 토큰)은 본문이 아니라 httpOnly 쿠키로. 본문에는 액세스 토큰만."""
    set_refresh_cookie(response, session.refresh_token)
    if session.device_token:
        set_device_cookie(response, session.device_token)  # 같은 브라우저의 예전 기기 쿠키는 이것으로 덮어쓴다
    _no_store(response)
    return LoginOk(**session.tokens.model_dump())


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
    response_model=SuccessResponse[LoginOk | DeviceChallenge],
    responses=error_responses(401, 403, 429),
)
async def login(
    data: UserLogin, db: Annotated[AsyncSession, Depends(get_db)], response: Response, request: Request
):
    ip = _ip(request)
    # IP 한도(여러 아이디를 찔러 보는 공격): 검증 전에 시도를 먼저 센다(넘었으면 429). 틀리면 그 기록이 그대로 실패 1회.
    # 같은 아이디를 계속 틀리는 것은 user_service.login의 DB 잠금(5회 연속, 채널별)이 막는다
    attempt = login_limiter.acquire(ip)
    # 기기 쿠키는 어느 채널로 셀지 정하는 데만 쓴다(인증 수단이 아님): 비밀번호가 여전히 필요하므로 CSRF 확인은 하지 않는다
    result = await user_service.login(db, data, request.cookies.get(DEVICE_COOKIE))
    login_limiter.reset(ip, attempt)
    _no_store(response)
    if isinstance(result, DeviceChallenge):
        # 새 기기: 세션도 쿠키도 주지 않는다. 휴대폰 인증 후 POST /users/login/device
        return SuccessResponse[LoginOk | DeviceChallenge](data=result, message="새 기기입니다. 휴대폰 인증이 필요합니다.")
    return SuccessResponse[LoginOk | DeviceChallenge](data=_login_ok(result, response))


@router.post(
    "/login/device/send",
    response_model=SuccessResponse[SendResponse],
    responses=error_responses(401, 429),
)
async def login_device_send(data: DeviceChallengeSend, request: Request, db: Annotated[AsyncSession, Depends(get_db)]):
    # send-for-me와 같은 응답·같은 발송 한도(번호당·IP당). 로그인 전이라 액세스 토큰 대신 challenge_token으로 본인을 확인한다
    verification_id = await user_service.login_device_send(db, data.challenge_token, _ip(request))
    return SuccessResponse[SendResponse](
        data=SendResponse(verification_id=verification_id, expires_in=int(CODE_TTL.total_seconds())),
        message="인증번호를 보냈습니다.",
    )


@router.post("/login/device", response_model=SuccessResponse[LoginOk], responses=error_responses(400, 401, 403))
async def login_device(
    data: DeviceLogin, db: Annotated[AsyncSession, Depends(get_db)], response: Response, request: Request
):
    # 인증번호 확인은 기존 POST /verification/phone/verify(로그인 불필요)를 그대로 쓴다. 여기서 그 증표를 소비하고 기기를 등록한다
    session = await user_service.login_device(
        db, data.challenge_token, data.phone_verification_token, request.headers.get("user-agent")
    )
    return SuccessResponse[LoginOk](data=_login_ok(session, response), message="새 기기가 등록되었습니다.")


# 세션이 이미 끝난 갱신 실패: 브라우저가 죽은 쿠키를 계속 보내지 않게 쿠키를 지운다.
# (그 밖의 실패에는 지우지 않는다: 일시적인 오류로 멀쩡한 세션을 잃으면 안 된다)
_DEAD_SESSION_CODES = {"INVALID_REFRESH_TOKEN", "REFRESH_TOKEN_REUSED", "SESSION_REPLACED"}


@router.post(
    "/token/refresh",
    response_model=SuccessResponse[TokenResponse],
    responses=error_responses(401, 403),
    dependencies=[Depends(require_allowed_origin)],
)
async def refresh_token(request: Request, db: Annotated[AsyncSession, Depends(get_db)], response: Response):
    # 액세스 토큰을 요구하지 않는다: 액세스 토큰이 만료됐을 때 부르는 API이기 때문이다. 본문 없이 쿠키만 받는다
    raw = request.cookies.get(REFRESH_COOKIE)
    try:
        if not raw:
            raise UnauthorizedException(message="로그인이 만료되었습니다. 다시 로그인해 주세요.", code="INVALID_REFRESH_TOKEN")
        session = await user_service.refresh(db, raw)
    except UnauthorizedException as e:
        # 폐기는 service.refresh가 이미 커밋하고 나서 던진 예외다. 여기서는 응답에 쿠키 삭제만 얹는다
        if e.code in _DEAD_SESSION_CODES:
            e.headers = {**(e.headers or {}), "Set-Cookie": clear_cookie_header(REFRESH_COOKIE)}
        raise
    set_refresh_cookie(response, session.refresh_token)
    _no_store(response)
    return SuccessResponse[TokenResponse](data=session.tokens)


@router.post(
    "/logout",
    response_model=SuccessResponse[None],
    responses=error_responses(403),
    dependencies=[Depends(require_allowed_origin)],
)
async def logout(request: Request, db: Annotated[AsyncSession, Depends(get_db)], response: Response):
    # 액세스 토큰이 만료된 상태에서도 로그아웃할 수 있어야 하므로 갱신 토큰 쿠키만 본다. 쿠키가 없어도 조용히 성공(멱등)
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        await user_service.logout(db, raw)
    # 서버 쪽 폐기와 별개로 브라우저의 쿠키도 지운다. 기기 쿠키는 남긴다: 기기 등록은 로그아웃과 무관하다
    clear_cookie(response, REFRESH_COOKIE)
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
    request: Request,
):
    # 현재 비밀번호 틀림은 로그인 실패와 같은 DB 카운터로 센다(5회면 로그인 잠금). 훔친 토큰으로 현재 비밀번호를
    # 알아내려는 시도를 막는다 (C-045 → C-090). 채널은 요청의 기기 쿠키로 정한다(등록 기기 / 새 기기)
    session = await user_service.change_password(db, current_user, data, request.cookies.get(DEVICE_COOKIE))
    set_refresh_cookie(response, session.refresh_token)  # 이 기기만 새 세션으로 이어진다
    _no_store(response)
    return SuccessResponse[TokenResponse](data=session.tokens, message="비밀번호가 변경되었습니다.")


@router.get("/me/devices", response_model=SuccessResponse[list[DeviceResponse]], responses=error_responses(401))
async def list_devices(
    current_user: Annotated[UserResponse, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
):
    rows = await user_service.list_devices(db, current_user, request.cookies.get(DEVICE_COOKIE))
    return SuccessResponse[list[DeviceResponse]](
        data=[
            DeviceResponse(
                device_id=d.device_id, label=d.label, created_at=d.created_at, last_used_at=d.last_used_at, current=current
            )
            for d, current in rows
        ]
    )


@router.delete(
    "/me/devices/{device_id}",
    response_model=SuccessResponse[None],
    responses=error_responses(401, 403, 404),
    dependencies=[Depends(require_allowed_origin)],  # 기기 쿠키를 읽고 지우므로 쿠키 요청과 같은 CSRF 확인
)
async def revoke_device(
    device_id: int,
    current_user: Annotated[UserResponse, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
    response: Response,
):
    if await user_service.revoke_device(db, current_user, device_id, request.cookies.get(DEVICE_COOKIE)):
        clear_cookie(response, DEVICE_COOKIE)  # 지금 이 브라우저의 기기였다. 해제해도 현재 세션은 이어진다
    return SuccessResponse[None](data=None, message="기기 등록을 해제했습니다.")


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


@router.get(
    "/me/withdrawal", response_model=SuccessResponse[WithdrawalStatus], responses=error_responses(401)
)
async def get_withdrawal(
    current_user: Annotated[UserResponse, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # 탈퇴할 수 있는지, 없으면 무엇을 먼저 해야 하는지 (예금·적금 해지, 잔액 옮기기, 카드 대금 납부)
    blockers = await withdrawal.get_blockers(db, current_user)
    return SuccessResponse[WithdrawalStatus](data=WithdrawalStatus(can_withdraw=not blockers, blockers=blockers))


@router.post(
    "/me/withdrawal", response_model=SuccessResponse[None], responses=error_responses(400, 401, 403, 429)
)
async def withdraw(
    data: WithdrawalRequest,
    current_user: Annotated[UserResponse, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
    response: Response,
):
    # 비밀번호 틀림은 로그인 실패와 같은 카운터(5회면 잠금, 채널은 기기 쿠키로). 막는 사유가 있으면 400 WITHDRAWAL_BLOCKED
    await withdrawal.withdraw(
        db, current_user, data.current_password, data.phone_verification_token, request.cookies.get(DEVICE_COOKIE)
    )
    # 세션과 기기는 서버에서 모두 끊겼다. 브라우저의 쿠키도 지운다
    clear_cookie(response, REFRESH_COOKIE)
    clear_cookie(response, DEVICE_COOKIE)
    return SuccessResponse[None](data=None, message="회원 탈퇴가 완료되었습니다. 그동안 이용해 주셔서 감사합니다.")
