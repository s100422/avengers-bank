"""계정 복구: 아이디 찾기·비밀번호 찾기 (은행형 — 계좌번호 + 계좌 비밀번호(아는 것) + 등록 휴대폰 인증번호(가진 것)).

배경은 docs/ACCOUNT_RECOVERY_RESEARCH.md. 로그인 5회 잠금은 이 비밀번호 찾기로만 풀린다(관리자 명령 제외).

흐름: start(정보 확인 → 맞으면 인증번호 발송, 언제나 같은 응답 + recovery_token)
     → verify(인증번호 확인 → 아이디 찾기는 끝, 비밀번호 찾기는 reset_token)
     → reset_password(reset_token 1회 사용 → 새 비밀번호, 잠금 해제, 모든 세션 폐기, 알림)

응답 동일화 (OWASP Forgot Password): 계좌가 없든, 계좌 비밀번호가 틀리든, 잠겼든, 아이디가 다르든 start는 같은 응답이다.
- recovery_token은 언제나 같은 모양의 서명된 JWT다. 정보가 맞으면 인증번호 행 번호(verification_id)를, 틀리면 0을
  '봉인'해 담는다: ref = vid XOR HMAC(서버 키, 무작위 nonce). JWT 본문은 누구나 읽을 수 있으므로 vid를 그대로 넣으면
  null/숫자로 정답 여부가 드러난다. 봉인하면 진짜·가짜 모두 무작위 16진수 16자로 보인다.
- 응답 시간: 계좌가 없거나·미설정·잠김이면 가짜 해시로 argon2를 한 번 돌린다(맞는 경우와 같은 비용).
  verify도 가짜 토큰이면 vid 0으로 같은 UPDATE를 실행한다(DB 왕복 한 번).
"""

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone

import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import ApiException, BadRequestException
from avengers_bank.core.login_limiter import TooManyAttemptsException, verification_ip_limiter
from avengers_bank.core.security import ALGORITHM, DUMMY_HASH, verify_password
from avengers_bank.domains.accounts.password import verify_account_password
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.users.repository import user_repository
from avengers_bank.domains.users.service import user_service
from avengers_bank.domains.verification.service import (
    MAX_ATTEMPTS,
    TOKEN_TTL,
    _expired,
    consume_verification,
    send_notice,
    start_verification,
    verify_code,
)

TOKEN_TYPE = "recovery"  # 액세스 토큰("sub"), 인증 증표("verification")와 섞이지 않게
PASSWORD_RESET, FIND_LOGIN_ID = "PASSWORD_RESET", "FIND_LOGIN_ID"
EXPIRES_IN = int(TOKEN_TTL.total_seconds())

# 가짜 recovery_token의 '틀린 횟수'. 진짜는 DB(verification_codes.attempts)가 세서 (1/5)…(5/5) 뒤 만료로 바뀐다.
# 가짜가 늘 (1/5)이면 두 번째 시도에서 가짜임이 드러나므로 nonce별로 똑같이 세어 준다.
# ponytail: 프로세스 메모리 (login_limiter와 같은 한계 — 재시작하면 초기화, 서버 여러 대면 각자 셈). 여러 대면 Redis로
_fake_attempts: dict[str, tuple[int, float]] = {}  # nonce → (틀린 횟수, 토큰 만료 시각 epoch)


def _secret() -> bytes:
    return get_settings().jwt_secret_key.get_secret_value().encode()


def _pad(nonce: str) -> int:
    return int.from_bytes(hmac.new(_secret(), f"recovery:{nonce}".encode(), hashlib.sha256).digest()[:8], "big")


def _issue(purpose: str, verification_id: int | None) -> str:
    now = datetime.now(timezone.utc)
    nonce = secrets.token_urlsafe(16)
    ref = (verification_id or 0) ^ _pad(nonce)
    payload = {"typ": TOKEN_TYPE, "purpose": purpose, "n": nonce, "ref": f"{ref:016x}", "iat": now, "exp": now + TOKEN_TTL}
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def _open(token: str) -> tuple[str, int, str, float]:
    """(purpose, verification_id(가짜면 0), nonce, 만료 시각). 만료·위조·깨진 토큰은 모두 '만료' — 다시 시작하면 된다."""
    try:
        p = jwt.decode(token, _secret(), algorithms=[ALGORITHM], options={"require": ["typ", "purpose", "n", "ref", "exp"]})
        if p["typ"] != TOKEN_TYPE or p["purpose"] not in (PASSWORD_RESET, FIND_LOGIN_ID):
            raise ValueError
        return p["purpose"], int(p["ref"], 16) ^ _pad(p["n"]), p["n"], float(p["exp"])
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise _expired() from None


def _fake_wrong_code(nonce: str, expires: float) -> BadRequestException:
    """가짜 토큰의 실패를 진짜 인증번호 오류와 같은 코드·문구·횟수로 만든다."""
    now = time.time()
    for key in [k for k, (_, exp) in _fake_attempts.items() if exp <= now]:
        del _fake_attempts[key]  # 만료된 기록은 버린다 (메모리가 계속 늘지 않게)
    attempts = _fake_attempts.get(nonce, (0, expires))[0] + 1
    if attempts > MAX_ATTEMPTS:
        return _expired()  # 진짜도 5번을 다 쓰면 만료로 바뀐다
    _fake_attempts[nonce] = (attempts, expires)
    return BadRequestException(
        code="INVALID_VERIFICATION_CODE", message=f"인증번호가 올바르지 않습니다. ({attempts}/{MAX_ATTEMPTS})"
    )


def mask_login_id(login_id: str) -> str:
    """앞 2자 + 마지막 1자만 보인다 (demo3 → de**3, abcd → ab*d). 3자 이하(예전 규칙 계정)는 첫 글자만."""
    if len(login_id) <= 3:
        return login_id[0] + "*" * (len(login_id) - 1)
    return login_id[:2] + "*" * (len(login_id) - 3) + login_id[-1]


async def start(
    db: AsyncSession, *, purpose: str, login_id: str | None, account_num: str, account_password: str, ip: str
) -> str:
    """정보가 맞으면 등록 휴대폰으로 인증번호를 보낸다. 맞든 틀리든 같은 모양의 recovery_token을 돌려준다.

    계좌 비밀번호는 기존 규칙 그대로 센다: 계좌가 있으면(아이디가 맞든 틀리든) 행을 잠그고 검증, 틀리면 +1, 5번째면 잠금.
    틀려도 예외로 끝내지 않으므로 증가가 이 트랜잭션과 함께 커밋된다(password.py의 '롤백 함정'을 피한다).
    """
    # 정보가 틀려 발송하지 않는 요청도 센다: 그래야 IP 하나로 계좌 비밀번호를 대량으로 찔러 볼 수 없다
    verification_ip_limiter.acquire(ip)
    target: tuple[int, str] | None = None  # (user_id, 등록 휴대폰)
    async with db.begin():
        account = await account_repository.lock_checking_by_account_num(db, account_num)
        if account is None or account.password_hash is None or account.password_locked_at is not None:
            await run_in_threadpool(verify_password, account_password, DUMMY_HASH)  # 응답 시간을 맞는 경우와 같게
        else:
            try:
                await verify_account_password(db, account, account_password)
                user = await user_repository.find_by_id(db, account.user_id)
                if purpose == FIND_LOGIN_ID or user.login_id == login_id:
                    target = (user.user_id, user.phone)
            except ApiException:
                pass  # 틀림(·5번째면 잠금): 증가를 커밋하고 같은 응답을 준다
    verification_id = None
    if target:
        try:
            verification_id = await start_verification(db, purpose=purpose, phone=target[1], user_id=target[0], ip=None)
        except TooManyAttemptsException:
            # 번호당 발송 제한(15분 3번)에 걸렸다. 429로 알리면 '정보가 맞았다'는 사실이 드러나므로 보내지 않고 같은 응답
            pass
    return _issue(purpose, verification_id)


async def verify(db: AsyncSession, recovery_token: str, code: str) -> dict:
    purpose, verification_id, nonce, expires = _open(recovery_token)
    try:
        # 가짜(0)도 같은 함수로: 같은 UPDATE가 실행되고(0행) 만료 예외가 난다 → 아래에서 '틀린 인증번호'로 바꾼다
        verification_token = await verify_code(db, verification_id, code)
    except BadRequestException as e:
        if verification_id == 0 and e.code == "VERIFICATION_EXPIRED":
            raise _fake_wrong_code(nonce, expires) from None
        raise
    if purpose == PASSWORD_RESET:
        # 아직 쓰지 않는다: 다음 단계(reset_password)에서 새 비밀번호와 같은 트랜잭션으로 1회 사용한다
        return {"reset_token": verification_token, "expires_in": EXPIRES_IN}
    async with db.begin():
        row = await consume_verification(db, verification_token, FIND_LOGIN_ID)
        user = await user_repository.find_by_id(db, row.user_id)
    # 화면에는 일부만, 전체 아이디는 휴대폰을 가진 사람에게만
    await send_notice(row.phone, f"아이디: {user.login_id}. 본인이 요청하지 않았다면 고객센터로 연락해 주세요.")
    return {"masked_login_id": mask_login_id(user.login_id)}


async def reset_password(db: AsyncSession, reset_token: str, new_password: str) -> None:
    """reset_token 1회 사용 → 새 비밀번호 + 로그인 잠금 해제 + 모든 세션 폐기(user_service.reset_password) + 알림 문자.

    자동 로그인은 하지 않는다(OWASP): 새 비밀번호로 직접 로그인하게 한다.
    규칙 위반(아이디와 같음·현재와 같음)은 증표 사용과 같은 트랜잭션에서 예외로 끝내 사용을 되돌린다 → 고쳐서 다시 보낼 수 있다.
    """
    async with db.begin():
        row = await consume_verification(db, reset_token, PASSWORD_RESET)
        user = await user_repository.find_by_id(db, row.user_id)
        if new_password.lower() == user.login_id.lower():
            raise BadRequestException(code="PASSWORD_SAME_AS_LOGIN_ID", message="비밀번호는 아이디와 같을 수 없습니다.")
        # 은행 관행: 재설정은 이전과 다른 비밀번호로 (현재 비밀번호를 기억했다면 찾기가 필요 없었다)
        if await run_in_threadpool(verify_password, new_password, user.hashed_password):
            raise BadRequestException(code="SAME_PASSWORD", message="새 비밀번호가 현재 비밀번호와 같습니다.")
        login_id, phone = user.login_id, user.phone
    # 증표는 위에서 커밋됐다. 바꾸기·잠금 해제·세션 폐기는 관리자 명령과 같은 함수 (사용자 행을 먼저 잠근다)
    await user_service.reset_password(db, login_id, new_password)
    await send_notice(phone, "비밀번호가 재설정되었습니다. 본인이 아니라면 바로 고객센터로 연락해 주세요.")
