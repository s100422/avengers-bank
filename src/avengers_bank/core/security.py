from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import UnauthorizedException

ALGORITHM = "HS256"
password_hash = PasswordHash.recommended()
# 없는 아이디로 로그인할 때도 비밀번호 검증과 같은 시간이 걸리게 하려는 가짜 해시.
# 없으면 응답 시간 차이(약 70ms vs 2ms)로 가입된 아이디를 알아낼 수 있다. 서버를 시작할 때 한 번 만든다.
DUMMY_HASH = password_hash.hash("dummy-password-for-constant-time-login")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return password_hash.verify(password, hashed_password)
    except UnknownHashError:
        return False


def create_access_token(user_id: int) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(
        payload, settings.jwt_secret_key.get_secret_value(), algorithm=ALGORITHM
    )


def decode_access_token(token: str) -> int:
    try:
        payload = jwt.decode(
            token,
            get_settings().jwt_secret_key.get_secret_value(),
            algorithms=[ALGORITHM],
            options={"require": ["sub", "iat", "exp"]},
        )
        return int(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise UnauthorizedException(
            message="유효하지 않거나 만료된 토큰입니다.", code="INVALID_TOKEN"
        ) from None
