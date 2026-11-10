"""휴대폰 인증번호 (C-090). 가입·번호 변경이 쓰고, 2단계(비밀번호 찾기·아이디 찾기·계좌 비밀번호 재설정)가 재사용한다.

흐름: start_verification(문자 발송) → verify_code(인증번호 확인, 증표 발급) → consume_verification(증표 1회 사용).
증표(verification_token)는 10분짜리 JWT다. 하지만 1회성은 JWT가 아니라 DB의 consumed_at이 보장한다.
"""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import BadRequestException
from avengers_bank.core.login_limiter import WINDOW_SECONDS, TooManyAttemptsException, verification_ip_limiter
from avengers_bank.core.security import ALGORITHM
from avengers_bank.domains.verification.models import VerificationCode
from avengers_bank.domains.verification.sms import send_sms

CODE_TTL = timedelta(minutes=10)  # 인증번호 유효 시간
TOKEN_TTL = timedelta(minutes=10)  # 확인 뒤 받은 증표의 유효 시간
MAX_ATTEMPTS = 5  # 인증번호 하나로 확인을 시도할 수 있는 횟수
MAX_SENDS_PER_PHONE = 3  # 같은 번호로 15분(WINDOW_SECONDS) 동안 보낼 수 있는 문자 수 (문자 폭탄·비용 방지)
TOKEN_TYPE = "verification"  # 액세스 토큰과 섞이지 않게 typ로 구분한다


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _code_hash(verification_id: int, code: str) -> str:
    """인증번호는 HMAC-SHA256(서버 비밀키, id + 코드)로만 저장한다.

    6자리 숫자는 경우의 수가 100만뿐이라 그냥 SHA-256이면 DB가 유출됐을 때 100만 번 해 보면 바로 원문이 나온다.
    서버 비밀키를 섞으면 DB만으로는 역산할 수 없다. verification_id를 섞어 같은 코드라도 행마다 값이 다르다.
    비밀키는 JWT 비밀키를 재사용한다(앞에 "verification:"을 붙여 용도를 나눈다). 키를 따로 돌려야(교체) 할 일이
    생기면 설정을 분리한다 — 지금은 키 하나가 새면 어차피 토큰 위조가 가능해 따로 두는 이득이 작다.
    """
    key = get_settings().jwt_secret_key.get_secret_value().encode()
    return hmac.new(key, f"verification:{verification_id}:{code}".encode(), hashlib.sha256).hexdigest()


async def _serialize_phone(db: AsyncSession, phone: str) -> None:
    """같은 번호의 발송을 한 줄로 세운다: '최근 발송 수 세기 → 새 행 추가' 사이에 다른 요청이 끼면 3번을 넘길 수 있다.

    아직 없는 행은 잠글 수 없으므로 번호로 만든 트랜잭션 잠금(advisory lock, 커밋하면 풀린다)을 쓴다.
    SQLite(테스트)에는 없고, 쓰기가 원래 한 번에 하나라 필요 없다.
    """
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(text("select pg_advisory_xact_lock(hashtext(:key))"), {"key": f"verification:{phone}"})


async def start_verification(
    db: AsyncSession, *, purpose: str, phone: str, user_id: int | None = None, ip: str | None,
    demo_code: str | None = None,
) -> int:
    """인증번호를 만들어 문자로 보내고 verification_id를 돌려준다. 트랜잭션을 직접 열므로 트랜잭션 밖에서 부른다.

    발송 제한: IP당 15분 10번(메모리), 번호당 15분 3번(DB에서 센다 — 서버 재시작·여러 대에도 유지). 넘으면 429.
    ip=None: 호출한 쪽이 IP 한도를 이미 셌다(계정 복구는 정보가 틀려 발송하지 않는 요청도 세야 해서 먼저 센다).
    """
    if ip is not None:
        verification_ip_limiter.acquire(ip)
    if demo_code is not None and (purpose != "NEW_DEVICE" or not re.fullmatch(r"\d{6}", demo_code)):
        raise ValueError("시연 코드는 새 기기 인증에만 사용할 수 있습니다.")
    code = demo_code if demo_code is not None else f"{secrets.randbelow(1_000_000):06d}"
    now = _now()
    async with db.begin():
        await _serialize_phone(db, phone)
        recent = (
            await db.scalars(
                select(VerificationCode.created_at)
                .where(VerificationCode.phone == phone, VerificationCode.created_at > now - timedelta(seconds=WINDOW_SECONDS))
                .order_by(VerificationCode.created_at)
            )
        ).all()
        if len(recent) >= MAX_SENDS_PER_PHONE:
            oldest = recent[0].replace(tzinfo=timezone.utc) if recent[0].tzinfo is None else recent[0]
            raise TooManyAttemptsException(
                max(1, int(WINDOW_SECONDS - (now - oldest).total_seconds()) + 1),
                verification_ip_limiter.code, verification_ip_limiter.message,
            )
        # created_at을 서버 기본값이 아니라 여기서 넣는다: 위의 '최근 15분' 비교와 같은 시계를 쓰게
        row = VerificationCode(
            purpose=purpose, phone=phone, user_id=user_id, code_hash="", expires_at=now + CODE_TTL, created_at=now
        )
        db.add(row)
        await db.flush()  # 해시에 verification_id가 들어가므로 먼저 id를 받는다
        row.code_hash = _code_hash(row.verification_id, code)
    # 커밋한 뒤 보낸다: 보냈는데 행이 없는(확인할 수 없는) 인증번호가 생기지 않게
    if demo_code is None:
        await send_sms(phone, f"[AvengersBank] 인증번호 {code} (10분 안에 입력). 타인에게 알려 주지 마세요.")
    return row.verification_id


def _expired() -> BadRequestException:
    return BadRequestException(code="VERIFICATION_EXPIRED", message="인증번호가 만료되었습니다. 다시 받아 주세요.")


async def verify_code(db: AsyncSession, verification_id: int, code: str) -> str:
    """인증번호를 확인하고 증표(verification_token)를 돌려준다.

    시도는 비교 *전에* 먼저 센다(로그인 잠금과 같은 원리): 'attempts < 5인 행만 +1' UPDATE 한 문장이라 동시 요청이
    몇 개가 와도 정확히 5번만 비교된다. 틀려도 그 +1은 커밋해야 하므로 예외는 트랜잭션 밖에서 던진다.
    """
    now = _now()
    vc = VerificationCode
    async with db.begin():
        counted = (
            await db.execute(
                update(vc)
                .where(
                    vc.verification_id == verification_id, vc.attempts < MAX_ATTEMPTS,
                    vc.verified_at.is_(None), vc.expires_at > now,
                )
                .values(attempts=vc.attempts + 1)
                .returning(vc.attempts, vc.code_hash, vc.purpose, vc.phone, vc.user_id)
            )
        ).one_or_none()
        if counted is None:
            raise _expired()  # 없는 id·만료·5회 다 씀·이미 확인함. 바뀐 것이 없으니 롤백돼도 된다
        attempts, code_hash, purpose, phone, user_id = counted
        ok = hmac.compare_digest(code_hash, _code_hash(verification_id, code))
        if ok:
            await db.execute(update(vc).where(vc.verification_id == verification_id).values(verified_at=now))
    if not ok:
        raise BadRequestException(
            code="INVALID_VERIFICATION_CODE", message=f"인증번호가 올바르지 않습니다. ({attempts}/{MAX_ATTEMPTS})"
        )
    payload = {
        "typ": TOKEN_TYPE, "vid": verification_id, "purpose": purpose, "phone": phone, "uid": user_id,
        "iat": now, "exp": now + TOKEN_TTL,
    }
    return jwt.encode(payload, get_settings().jwt_secret_key.get_secret_value(), algorithm=ALGORITHM)


async def consume_verification(
    db: AsyncSession, token: str, purpose: str, *, phone: str | None = None, user_id: int | None = None
) -> VerificationCode:
    """증표를 검사하고 1회 사용 처리한다. 호출하는 쪽의 트랜잭션 안에서 부른다(그 작업이 롤백되면 사용도 되돌려진다).

    1회성: 'consumed_at IS NULL인 행만 채우는' UPDATE 한 문장이라, 같은 증표로 동시에 두 번 와도 한 번만 성공한다
    (그 행에 쓰기 잠금이 걸려 두 번째 UPDATE는 첫 번째 커밋을 기다린 뒤 조건이 안 맞아 0행).
    purpose·phone·user_id는 JWT 내용이 아니라 DB 행으로 확인한다(서명된 값이지만 DB가 최종 판정).
    """
    invalid = BadRequestException(
        code="INVALID_VERIFICATION_TOKEN", message="휴대폰 인증이 만료되었거나 올바르지 않습니다. 인증번호를 다시 받아 주세요."
    )
    try:
        payload = jwt.decode(
            token, get_settings().jwt_secret_key.get_secret_value(), algorithms=[ALGORITHM],
            options={"require": ["typ", "vid", "purpose", "exp"]},
        )
    except jwt.InvalidTokenError:
        raise invalid from None
    if payload["typ"] != TOKEN_TYPE or payload["purpose"] != purpose or not isinstance(payload["vid"], int):
        raise invalid
    vc = VerificationCode
    stmt = update(vc).where(
        vc.verification_id == payload["vid"], vc.purpose == purpose,
        vc.verified_at.is_not(None), vc.consumed_at.is_(None),
    )
    if phone is not None:
        stmt = stmt.where(vc.phone == phone)
    if user_id is not None:
        stmt = stmt.where(vc.user_id == user_id)
    row = await db.scalar(stmt.values(consumed_at=_now()).returning(vc))
    if row is None:
        raise invalid
    return row


async def send_notice(phone: str, text: str) -> None:
    """인증번호 없는 알림 문자 (예: 비밀번호가 재설정되었습니다)."""
    await send_sms(phone, f"[AvengersBank] {text}")
