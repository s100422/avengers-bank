import hashlib
import secrets
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


def create_access_token(user_id: int, session_id: str) -> str:
    """짧은 수명(기본 5분)의 JWT. `sid`에 이 토큰이 속한 세션(갱신 토큰의 family_id)을 담는다.

    처음(C-083)에는 서버가 아무것도 확인하지 않는 순수 JWT였다. 빠르지만 로그아웃해도 이미 발급된
    토큰은 최대 5분 더 쓸 수 있었다. 은행에서는 받아들이기 어려워서(C-087) 요청마다 `sid`의 세션이
    살아 있는지 DB에서 확인한다(users/service.py get_current_user). 그래서 로그아웃·비밀번호 변경이 즉시
    적용된다. 5분 만료는 남겨 둔다: 서명만으로 걸러지는 1차 방어이자, 세션 확인이 빠져도 오래 못 쓰게 하는 안전장치다.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "sid": session_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(
        payload, settings.jwt_secret_key.get_secret_value(), algorithm=ALGORITHM
    )


def decode_access_token(token: str) -> tuple[int, str]:
    """서명·만료를 검사하고 (사용자 id, 세션 id)를 돌려준다. 세션이 살아 있는지는 호출한 쪽이 DB로 확인한다."""
    try:
        payload = jwt.decode(
            token,
            get_settings().jwt_secret_key.get_secret_value(),
            algorithms=[ALGORITHM],
            options={"require": ["sub", "sid", "iat", "exp"]},  # sid 없는 예전 토큰은 거절 → 프론트가 갱신해서 새로 받는다
        )
        if not isinstance(payload["sid"], str):
            raise TypeError
        return int(payload["sub"]), payload["sid"]
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise UnauthorizedException(
            message="유효하지 않거나 만료된 토큰입니다.", code="INVALID_TOKEN"
        ) from None


def new_refresh_token() -> str:
    """갱신 토큰 원문. JWT가 아니라 아무 의미 없는 임의 문자열(256비트)이다.

    내용을 담을 필요가 없다: 서버가 DB에서 찾아 보고 판단하므로, 위조·추측만 불가능하면 된다.
    """
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """DB에는 원문 대신 이 해시만 저장한다. DB가 유출돼도 해시로는 갱신 요청을 할 수 없다.

    비밀번호와 달리 argon2(느린 해시)가 아니라 SHA-256을 쓴다: 원문이 256비트 임의값이라 대입 공격이
    불가능하므로 느릴 이유가 없고, 같은 입력 → 같은 해시라서 unique 인덱스로 바로 찾을 수 있다.
    """
    return hashlib.sha256(token.encode()).hexdigest()


CHALLENGE_TYPE = "device_challenge"  # 액세스 토큰·인증 증표와 섞이지 않게 typ로 구분한다
CHALLENGE_TTL = timedelta(minutes=10)


def create_device_challenge(user_id: int) -> str:
    """새 기기 로그인에서 비밀번호까지 맞았다는 증명(10분). 세션이 아니다: 이것만으로는 어떤 API도 못 쓴다.

    1회성은 JWT가 아니라 마지막 단계가 소비하는 휴대폰 인증 행(verification_codes.consumed_at)이 보장한다.
    이 토큰으로 인증번호를 여러 번 받을 수는 있지만(발송 한도 적용) 기기를 등록하려면 매번 새 인증이 필요하다.
    """
    now = datetime.now(timezone.utc)
    payload = {"typ": CHALLENGE_TYPE, "sub": str(user_id), "iat": now, "exp": now + CHALLENGE_TTL}
    return jwt.encode(payload, get_settings().jwt_secret_key.get_secret_value(), algorithm=ALGORITHM)


def decode_device_challenge(token: str) -> int:
    try:
        payload = jwt.decode(
            token, get_settings().jwt_secret_key.get_secret_value(), algorithms=[ALGORITHM],
            options={"require": ["typ", "sub", "exp"]},
        )
        if payload["typ"] != CHALLENGE_TYPE:
            raise ValueError
        return int(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise UnauthorizedException(
            message="기기 확인이 만료되었습니다. 다시 로그인해 주세요.", code="INVALID_DEVICE_CHALLENGE"
        ) from None
