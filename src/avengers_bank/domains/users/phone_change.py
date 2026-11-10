"""Phone number change workflow, kept separate from the broader user service."""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from avengers_bank.core.exceptions import (
    ApiException,
    BadRequestException,
    ForbiddenException,
    UnauthorizedException,
)
from avengers_bank.core.security import hash_refresh_token, verify_password
from avengers_bank.domains.users.models import User
from avengers_bank.domains.users.repository import user_repository
from avengers_bank.domains.users.schemas import PhoneChange, UserResponse
from avengers_bank.domains.verification.service import consume_verification

MAX_LOGIN_FAILURES = 5
ACCOUNT_LOCKED_MESSAGE = "비밀번호를 5회 잘못 입력해 로그인이 잠겼습니다. 비밀번호 찾기에서 본인 확인 후 해제해 주세요."


def _locked() -> ForbiddenException:
    return ForbiddenException(message=ACCOUNT_LOCKED_MESSAGE, code="ACCOUNT_LOCKED")


def _busy() -> ApiException:
    """선증가가 거절됐는데 잠긴 건 아닐 때: 동시에 온 요청들이 시도 5번을 이미 다 가져가 검증 중이다.

    '잠겼다'고 하면 맞는 비밀번호로 동시에 6번 이상 보낸 사용자에게 틀린 안내가 된다(실제로는 안 잠김).
    """
    return ApiException(
        429, "TOO_MANY_LOGIN_ATTEMPTS", "로그인 요청이 동시에 너무 많습니다. 잠시 후 다시 시도해 주세요.",
        headers={"Retry-After": "1"},
    )


async def change_phone(
    db: AsyncSession,
    current_user: UserResponse,
    data: PhoneChange,
    raw_device_token: str | None = None,
) -> User:
    # A password check follows login's per-channel failure counter and locking rules.
    async with db.begin():
        device = False
        if raw_device_token:
            device = await user_repository.find_active_device(
                db, current_user.user_id, hash_refresh_token(raw_device_token)
            ) is not None
        count = await user_repository.count_login_attempt(db, current_user.user_id, MAX_LOGIN_FAILURES, device)
        found = await user_repository.find_by_id(db, current_user.user_id)
        locked = count is None and found is not None and found.login_locked(device)
    if count is None:
        raise _locked() if locked else _busy()

    wrong = False
    async with db.begin():
        user = await user_repository.lock_user(db, current_user.user_id)
        if user is None or user.deleted_at is not None:
            raise UnauthorizedException(message="유효하지 않거나 만료된 토큰입니다.", code="INVALID_TOKEN")
        if user.login_locked(device):
            raise _locked()
        if not await run_in_threadpool(verify_password, data.current_password, user.hashed_password):
            if count >= MAX_LOGIN_FAILURES:
                await user_repository.lock_login(db, user.user_id, datetime.now(timezone.utc), MAX_LOGIN_FAILURES, device)
            wrong = True
        else:
            now = datetime.now(timezone.utc)
            # Both proofs are bound to this account and their respective numbers; consumption and mutation commit together.
            await consume_verification(db, data.old_phone_verification_token, "CHANGE_PHONE_OLD", phone=user.phone, user_id=user.user_id)
            await consume_verification(db, data.new_phone_verification_token, "CHANGE_PHONE_NEW", phone=data.phone, user_id=user.user_id)
            user.phone = data.phone
            user.phone_verified_at = now
            user.reset_login_failures(device)
            await user_repository.revoke_user_refresh_tokens(db, user.user_id, now, "PHONE_CHANGED")
            await user_repository.revoke_user_devices(db, user.user_id, now)
    if wrong:
        if count >= MAX_LOGIN_FAILURES:
            raise _locked()
        raise BadRequestException(code="INVALID_CURRENT_PASSWORD", message="현재 비밀번호가 올바르지 않습니다.")
    return user
