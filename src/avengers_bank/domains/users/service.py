import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import (
    ApiException,
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from avengers_bank.core.security import (
    DUMMY_HASH,
    create_access_token,
    create_device_challenge,
    decode_access_token,
    decode_device_challenge,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from avengers_bank.domains.users.models import RefreshToken, User, UserDevice
from avengers_bank.domains.users.phone_change import change_phone as run_phone_change
from avengers_bank.domains.users.repository import user_repository
from avengers_bank.domains.users.schemas import (
    DeviceChallenge,
    PasswordChange,
    PhoneChange,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
)
from avengers_bank.domains.verification.service import consume_verification, start_verification

SESSION_EXPIRED_MESSAGE = "로그인이 만료되었습니다. 다시 로그인해 주세요."
SESSION_REPLACED_MESSAGE = "다른 곳에서 로그인되어 로그아웃되었습니다."
LOGIN_ELSEWHERE = "LOGIN_ELSEWHERE"  # 폐기 이유 (models.REVOKED_REASONS)
# 로그인 잠금 (C-090, 전자금융감독규정 제33조: 5회 이내 오류 시 거래 중지, 본인 확인 후 재부여)
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


def _as_utc(moment: datetime) -> datetime:
    # SQLite(테스트)는 시간대를 버리고 돌려준다. 저장할 때 UTC였으므로 UTC로 붙인다
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


class Session(NamedTuple):
    """로그인·갱신의 결과. 갱신 토큰(과 새로 등록한 기기 토큰)은 본문이 아니라 라우터가 httpOnly 쿠키로 내린다."""

    tokens: TokenResponse
    refresh_token: str
    device_token: str | None = None  # 이번에 새 기기를 등록했을 때만


def mask_phone(phone: str) -> str:
    """010-1234-5678 → 010-****-5678 (가운데만 가린다)."""
    parts = phone.split("-")
    return f"{parts[0]}-****-{parts[-1]}" if len(parts) == 3 else "*" * max(len(phone) - 4, 0) + phone[-4:]


def device_label(user_agent: str | None) -> str:
    """User-Agent에서 "Chrome · Windows" 같은 짧은 이름만 뽑는다. 헤더는 클라이언트가 정하는 값이라 원문은 저장하지 않는다.

    목록 순서가 중요하다: Edge·Opera의 UA에도 'Chrome'이, Chrome의 UA에도 'Safari'가 들어 있다.
    """
    ua = user_agent or ""
    browser = next((n for p, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari")) if p in ua), "알 수 없는 브라우저")
    system = next((n for p, n in (("iPhone", "iOS"), ("iPad", "iOS"), ("Android", "Android"), ("Windows", "Windows"), ("Mac OS X", "macOS"), ("Linux", "Linux")) if re.search(p, ua)), "알 수 없는 기기")
    return f"{browser} · {system}"[:100]


class UserService:
    async def _issue_tokens(
        self, db: AsyncSession, user_id: int, family_id: str, now: datetime
    ) -> tuple[RefreshToken, Session]:
        """새 액세스 토큰 + 새 갱신 토큰. 갱신 토큰은 해시만 저장하고 원문은 쿠키로 한 번만 내보낸다."""
        settings = get_settings()
        raw = new_refresh_token()
        # 슬라이딩 세션: 갱신할 때마다 '지금부터 30분'으로 새로 잡는다. 30분 동안 갱신이 없으면 끝
        expires_at = now + timedelta(minutes=settings.session_expire_minutes)
        row = await user_repository.save_refresh_token(
            db, RefreshToken(user_id=user_id, family_id=family_id, token_hash=hash_refresh_token(raw), expires_at=expires_at)
        )
        tokens = TokenResponse(
            access_token=create_access_token(user_id, family_id),
            expires_in=settings.access_token_expire_minutes * 60,
            session_expires_at=expires_at,
        )
        return row, Session(tokens, raw)

    async def _start_session(self, db: AsyncSession, user: User, now: datetime) -> Session:
        """로그인 성공 공통(등록 기기·새 기기 인증 후). 호출하는 쪽이 user를 lock_user로 잠근 트랜잭션 안에서 부른다.

        단일 세션: 다른 곳에서 로그인하면 기존 세션을 모두 끊는다. 잠그지 않으면 동시 로그인 두 개가
        서로의 커밋 전 새 행을 못 봐 둘 다 살아남는다(lock_user 설명). 끊긴 기기의 액세스 토큰도 다음 요청부터 401(C-087).
        """
        await user_repository.revoke_user_refresh_tokens(db, user.user_id, now, LOGIN_ELSEWHERE)
        # 로그인 1번 = 새 family(세션) 1개. 이후 갱신 토큰은 이 family 안에서 이어진다
        _, session = await self._issue_tokens(db, user.user_id, str(uuid.uuid4()), now)
        return session

    async def _is_registered_device(self, db: AsyncSession, user_id: int, raw_device_token: str | None) -> bool:
        """로그인 채널을 정한다: 이 사용자의 해제되지 않은 기기 쿠키면 '등록 기기', 아니면(없음·해제·남의 쿠키) '새 기기'.

        비밀번호를 검증하기 *전에* 정해야 한다: 어느 채널의 카운터를 먼저 세고 잠금을 볼지가 여기서 갈린다.
        트랜잭션 안에서 부른다.
        """
        if not raw_device_token:
            return False
        return await user_repository.find_active_device(db, user_id, hash_refresh_token(raw_device_token)) is not None

    async def signup(self, db: AsyncSession, data: UserCreate) -> User:
        hashed_password = await run_in_threadpool(hash_password, data.password)
        duplicate = ConflictException(
            code="LOGIN_ID_ALREADY_EXISTS", message="이미 사용 중인 아이디입니다."
        )

        try:
            async with db.begin():
                if await user_repository.find_by_login_id(db, data.login_id) is not None:
                    raise duplicate
                # 휴대폰 인증 증표를 같은 트랜잭션 안에서 쓴다: 가입이 실패(중복 등)해 롤백되면 증표 사용도 되돌려져
                # 다시 쓸 수 있고, 성공하면 정확히 한 번 쓰인 것으로 남는다
                await consume_verification(db, data.phone_verification_token, "SIGNUP_PHONE", phone=data.phone)
                user = User(
                    login_id=data.login_id,
                    hashed_password=hashed_password,
                    name=data.name,
                    nick_name=data.nick_name,
                    phone=data.phone,
                    phone_verified_at=datetime.now(timezone.utc),
                )
                await user_repository.save(db, user)
                await db.refresh(user)
        except IntegrityError:
            # 동시 가입 요청이 위 조회를 함께 통과하면 DB unique 제약이 최종 판정한다.
            raise duplicate from None

        return user

    async def login(
        self, db: AsyncSession, data: UserLogin, raw_device_token: str | None = None
    ) -> Session | DeviceChallenge:
        """은행식 로그인 잠금 (C-090): 같은 아이디로 5회 연속 틀리면 잠그고, 잠기면 맞는 비밀번호도 거절한다.

        순서: 아이디 조회 → 채널 결정 → 잠겼으면 403 → 실패 1회를 *먼저* 센다(커밋) → 비밀번호 검증 → 맞으면 0으로, 5번째로 틀리면 잠금.

        채널(B1): 기기 쿠키가 이 사용자의 등록 기기면 '등록 기기', 아니면 '새 기기'. 카운터·잠금이 채널마다 따로라서
        남이 새 기기 채널을 틀려서 잠가도 주인은 등록 기기로 로그인한다. 성공은 그 채널의 카운터만 0으로 한다.
        새 기기는 비밀번호가 맞아도 세션을 주지 않고 DeviceChallenge(휴대폰 인증을 더 하라)를 돌려준다.
        """
        invalid = UnauthorizedException(
            message="아이디 또는 비밀번호가 올바르지 않습니다.", code="INVALID_CREDENTIALS"
        )
        # 1) 선증가는 자기 트랜잭션에서 검증 *전에* 커밋한다. 그래서 아래에서 어떤 예외(401·403·서버 오류)가 나도
        #    되돌려지지 않는다. 증가가 롤백될 수 있으면 틀릴 때마다 카운트가 사라져 잠금이 무력해진다.
        async with db.begin():
            user = await user_repository.find_by_login_id(db, data.login_id)
            if user is not None and user.deleted_at is not None:
                user = None  # 탈퇴 회원은 없는 아이디와 똑같이(가짜 해시 검증 → 401). 실패도 세지 않는다(잠금 403이 존재를 드러냄)
            count = None
            device = False
            if user is not None:
                device = await self._is_registered_device(db, user.user_id, raw_device_token)
                if not user.login_locked(device):
                    count = await user_repository.count_login_attempt(db, user.user_id, MAX_LOGIN_FAILURES, device)
        if user is None:
            # 없는 아이디도 가짜 해시로 검증해서 응답 시간으로 아이디 존재를 알 수 없게 한다. 행이 없으니 잠금도 없다(IP 한도만)
            await run_in_threadpool(verify_password, data.password, DUMMY_HASH)
            raise invalid
        if count is None:
            # 검증하지 않는다. 이미 잠겼으면 403, 아니면 동시에 온 요청들이 5번을 다 가져간 것이라 429
            raise _locked() if user.login_locked(device) else _busy()

        # 2) 검증은 트랜잭션·행 잠금 밖에서 한다(약 70ms): 틀린 비밀번호 요청이 사용자 행을 붙잡지 않게
        if not await run_in_threadpool(verify_password, data.password, user.hashed_password):
            if count >= MAX_LOGIN_FAILURES:
                async with db.begin():  # 잠금도 커밋한 뒤에 알린다
                    await user_repository.lock_login(db, user.user_id, datetime.now(timezone.utc), MAX_LOGIN_FAILURES, device)
                raise _locked()
            raise invalid

        # 3) 성공
        async with db.begin():
            user = await user_repository.lock_user(db, user.user_id)
            if user is None:
                raise invalid
            if user.login_locked(device):
                raise _locked()  # 검증하는 사이에 다른 요청의 5번째 실패로 잠겼다: 잠기면 맞는 비밀번호도 거절
            user.reset_login_failures(device)  # '연속' 실패만 센다. 이 채널만
            now = datetime.now(timezone.utc)
            if not device:
                # 새 기기: 비밀번호는 맞았으므로 카운터는 0으로 두되(위) 세션은 아직 주지 않는다(휴대폰 인증 필요, login_device)
                return DeviceChallenge(challenge_token=create_device_challenge(user.user_id), phone_masked=mask_phone(user.phone))
            # 등록 기기: 휴대폰 인증 생략. 쿠키 해시로 다시 찾아 사용 시각을 갱신한다
            registered = await user_repository.find_active_device(db, user.user_id, hash_refresh_token(raw_device_token))
            if registered is None:
                raise invalid  # 검증하는 사이에 기기가 해제됐다: 새 기기 채널을 거치지 않았으니 다시 로그인하게 한다
            registered.last_used_at = now
            return await self._start_session(db, user, now)

    async def login_device_send(
        self, db: AsyncSession, challenge_token: str, ip: str | None
    ) -> tuple[int, bool]:
        """새 기기 인증번호를 *등록된* 번호로 보낸다(요청에 번호를 받지 않는다: 남의 번호로 보내게 할 수 없다).

        인증은 challenge_token(비밀번호가 맞았다는 증명)뿐이다. 발송 제한은 start_verification의 번호당·IP당 한도 그대로.
        """
        user_id = decode_device_challenge(challenge_token)
        async with db.begin():
            user = await user_repository.find_by_id(db, user_id)
            if user is None or user.deleted_at is not None:
                raise UnauthorizedException(message="기기 확인이 만료되었습니다. 다시 로그인해 주세요.", code="INVALID_DEVICE_CHALLENGE")
            phone = user.phone
            settings = get_settings()
            demo = bool(
                settings.demo_device_code is not None
                and settings.demo_device_login_id == user.login_id
                and settings.demo_device_phone == phone
                and settings.demo_device_until is not None
                and datetime.now(timezone.utc) < settings.demo_device_until
            )
            demo_code = settings.demo_device_code.get_secret_value() if demo else None
        verification_id = await start_verification(
            db, purpose="NEW_DEVICE", phone=phone, user_id=user_id, ip=ip, demo_code=demo_code
        )
        return verification_id, demo

    async def login_device(
        self, db: AsyncSession, challenge_token: str, phone_verification_token: str, user_agent: str | None
    ) -> Session:
        """새 기기 로그인 마무리: 인증 증표 소비 + 단일 세션 + 기기 등록 + 토큰 발급을 한 트랜잭션에서.

        1회성: 증표 소비(consumed_at IS NULL인 행만 채우는 UPDATE)가 이 트랜잭션 안에 있어, 같은 증표로 두 번째는 실패하고
        기기 등록이 중간에 실패하면 소비도 되돌려진다. challenge_token 자체는 10분 안이면 다시 쓸 수 있지만 기기를
        등록하려면 매번 새 휴대폰 인증이 필요하다(전화를 가진 사람만 통과).
        """
        user_id = decode_device_challenge(challenge_token)
        async with db.begin():
            user = await user_repository.lock_user(db, user_id)
            if user is None or user.deleted_at is not None:
                raise UnauthorizedException(message="기기 확인이 만료되었습니다. 다시 로그인해 주세요.", code="INVALID_DEVICE_CHALLENGE")
            if user.login_locked(False):
                raise _locked()  # 새 기기 채널이 잠겼다(챌린지를 받은 뒤 누가 틀려서 잠금): 잠금은 비밀번호 찾기로만 푼다
            await consume_verification(db, phone_verification_token, "NEW_DEVICE", phone=user.phone, user_id=user_id)
            now = datetime.now(timezone.utc)
            raw_device = new_refresh_token()
            db.add(UserDevice(user_id=user_id, token_hash=hash_refresh_token(raw_device), label=device_label(user_agent), last_used_at=now))
            session = await self._start_session(db, user, now)
        return session._replace(device_token=raw_device)

    async def refresh(self, db: AsyncSession, raw_token: str) -> Session:
        """갱신 토큰 회전(rotation): 쓴 토큰은 폐기하고 같은 family로 새 토큰을 준다.

        회전하는 이유: 갱신 토큰을 한 번만 쓸 수 있게 하면, 누가 훔쳐서 쓰면 진짜 사용자와 공격자 중
        나중에 쓰는 쪽이 "이미 교체된 토큰"을 내밀게 된다. 서버는 누가 공격자인지 모르므로 family(세션) 전체를 끊는다.
        """
        now = datetime.now(timezone.utc)
        invalid = UnauthorizedException(message=SESSION_EXPIRED_MESSAGE, code="INVALID_REFRESH_TOKEN")
        reused = False
        token_hash = hash_refresh_token(raw_token)
        async with db.begin():
            # 잠금 순서 users → refresh_tokens 를 지키려고: 잠그지 않고 찾아 user_id만 알아낸 뒤 사용자 행을 잠근다.
            # 사용자 잠금이 없으면 회전으로 INSERT한 새 행을 동시에 실행된 다른 곳 로그인·비밀번호 변경이 못 보고 놓친다
            token = await user_repository.find_refresh_token(db, token_hash)
            if token is None or await user_repository.lock_user(db, token.user_id) is None:
                raise invalid
            # 잠근 뒤 검사한다: 위에서 읽은 값은 낡았을 수 있다(같은 토큰으로 동시에 두 번 갱신하면 두 번째는
            # 여기서 첫 번째의 교체 결과를 보고 재사용으로 걸린다). FOR UPDATE + populate_existing으로 다시 읽는다
            token = await user_repository.find_refresh_token(db, token_hash, for_update=True)
            if token.replaced_by_id is not None:
                # 폐기를 커밋해야 하므로 여기서 raise하지 않는다(raise하면 begin()이 롤백한다). 블록 밖에서 401
                await user_repository.revoke_refresh_family(db, token.family_id, now, "REUSE_DETECTED")
                reused = True
            elif token.revoked_reason == LOGIN_ELSEWHERE:
                # 교체된 적 없이 '다른 곳 로그인'으로 끊긴 세션: 끊긴 기기에 이유를 알려 준다
                raise UnauthorizedException(message=SESSION_REPLACED_MESSAGE, code="SESSION_REPLACED")
            elif token.revoked_at is not None or _as_utc(token.expires_at) <= now:
                raise invalid  # 로그아웃·비밀번호 변경·재사용 감지로 끊긴 세션, 또는 30분 미사용
            else:
                new_row, session = await self._issue_tokens(db, token.user_id, token.family_id, now)
                token.revoked_at = now
                token.revoked_reason = "ROTATED"
                token.replaced_by_id = new_row.refresh_token_id
        if reused:
            raise UnauthorizedException(message=SESSION_EXPIRED_MESSAGE, code="REFRESH_TOKEN_REUSED")
        return session

    async def logout(self, db: AsyncSession, raw_token: str) -> None:
        """그 토큰의 family(=이 기기의 세션)를 끊는다. 모르는·이미 끊긴 토큰이어도 조용히 성공(멱등).

        그 세션의 액세스 토큰도 다음 요청부터 바로 거절된다(get_current_user가 세션을 확인, C-087).

        family 하나만 끊지만 사용자 잠금은 필요하다: 같은 브라우저의 다른 탭이 이 family를 동시에 갱신하면
        회전으로 생긴 새 행(커밋 전)을 폐기 UPDATE가 못 보고, 로그아웃했는데 새 토큰으로 세션이 이어진다.
        """
        async with db.begin():
            token = await user_repository.find_refresh_token(db, hash_refresh_token(raw_token))
            if token is not None and await user_repository.lock_user(db, token.user_id) is not None:
                await user_repository.revoke_refresh_family(db, token.family_id, datetime.now(timezone.utc), "LOGOUT")

    async def logout_all(self, db: AsyncSession, current_user: UserResponse) -> None:
        """이 사용자의 모든 세션(이 기기 포함)을 끊는다. 비밀번호 변경과 같은 폐기이지만 새 세션은 주지 않는다.

        로그아웃 버튼은 이 기기만(logout), "모든 기기에서 로그아웃"은 이것 — 다른 기기에서 로그인해 둔 것이
        걱정될 때 쓴다. 다른 기기의 액세스 토큰도 다음 요청부터 바로 거절된다(C-087).
        """
        async with db.begin():
            # 먼저 잠근다: 다른 기기가 지금 갱신 중이면 그 새 행(커밋 전)을 놓쳐 그 기기만 살아남는다(lock_user 설명)
            if await user_repository.lock_user(db, current_user.user_id) is None:
                raise UnauthorizedException(message="유효하지 않거나 만료된 토큰입니다.", code="INVALID_TOKEN")
            await user_repository.revoke_user_refresh_tokens(
                db, current_user.user_id, datetime.now(timezone.utc), "LOGOUT_ALL"
            )

    async def get_current_user(self, db: AsyncSession, token: str) -> User:
        user_id, session_id = decode_access_token(token)
        user = await user_repository.find_by_id(db, user_id)
        # 세션이 끊겼으면(로그아웃·모든 기기 로그아웃·비밀번호 변경·재사용 감지) 5분이 남았어도 바로 거절한다 (C-087).
        # 요청마다 인덱스 조회가 하나 늘지만, 어차피 위에서 사용자를 DB에서 읽고 있어 비용 차이는 작다
        # deleted_at: 탈퇴하면 세션도 모두 끊기지만(WITHDRAWN), 세션 확인이 빠지는 실수에 대비해 한 번 더 막는다
        if user is None or user.deleted_at is not None or not await user_repository.is_session_active(db, user_id, session_id):
            raise UnauthorizedException(
                message="유효하지 않거나 만료된 토큰입니다.", code="INVALID_TOKEN"
            )
        return user

    async def update_me(self, db: AsyncSession, current_user: UserResponse, data: UserUpdate) -> User:
        async with db.begin():
            user = await user_repository.find_by_id(db, current_user.user_id)
            if user is None:
                raise UnauthorizedException(
                    message="유효하지 않거나 만료된 토큰입니다.", code="INVALID_TOKEN"
                )
            for field, value in data.model_dump(exclude_unset=True).items():
                setattr(user, field, value)
        return user

    async def change_phone(
        self, db: AsyncSession, current_user: UserResponse, data: PhoneChange, raw_device_token: str | None = None
    ) -> User:
        return await run_phone_change(db, current_user, data, raw_device_token)

    async def unlock_login(self, db: AsyncSession, login_id: str) -> bool:
        """로그인 잠금 해제 + 실패 횟수 0 (새 기기·등록 기기 두 채널 모두). 개발용 API·관리자 명령이 쓴다. 없는 아이디면 False."""
        async with db.begin():
            return await user_repository.unlock_login(db, login_id)

    async def reset_password(self, db: AsyncSession, login_id: str, new_password: str) -> bool:
        """새 비밀번호로 바꾸고, 두 채널의 잠금을 풀고, 모든 세션과 등록 기기를 끊는다(관리자 명령, 비밀번호 찾기). 없는 아이디면 False.

        기기를 모두 해제하는 이유: 비밀번호를 잊어 재설정한다는 것은 누가 알고 있었을 수 있다는 뜻이고, 이미 등록된
        기기 쿠키가 있으면 새 비밀번호만으로 휴대폰 인증 없이 들어올 수 있다. 다음 로그인부터 다시 인증해 등록한다.
        (비밀번호 *변경*은 로그인한 본인이 현재 비밀번호를 알고 하는 것이라 기기를 유지한다.)

        새 비밀번호 규칙(validators.NewPassword, 아이디와 다름)은 호출하는 쪽이 검사한다.
        """
        new_hash = await run_in_threadpool(hash_password, new_password)
        async with db.begin():
            found = await user_repository.find_by_login_id(db, login_id)
            user = found and await user_repository.lock_user(db, found.user_id)  # 세션 폐기 전 잠금 (lock_user 설명)
            if not user or user.deleted_at is not None:  # 탈퇴 회원은 없는 아이디로 본다
                return False
            user.hashed_password = new_hash
            user.failed_login_count = 0
            user.login_locked_at = None
            user.device_failed_login_count = 0
            user.device_login_locked_at = None
            now = datetime.now(timezone.utc)
            await user_repository.revoke_user_refresh_tokens(db, user.user_id, now, "PASSWORD_CHANGED")
            await user_repository.revoke_user_devices(db, user.user_id, now)
        return True

    async def change_password(
        self, db: AsyncSession, current_user: UserResponse, data: PasswordChange, raw_device_token: str | None = None
    ) -> Session:
        if data.new_password == data.current_password:
            raise BadRequestException(code="SAME_PASSWORD", message="새 비밀번호가 현재 비밀번호와 같습니다.")
        # 강도 규칙은 PasswordChange 스키마가 본다. 아이디는 스키마가 모르므로 여기서 비교한다(가입과 같게 대소문자 무시)
        if data.new_password.lower() == current_user.login_id.lower():
            raise BadRequestException(code="PASSWORD_SAME_AS_LOGIN_ID", message="비밀번호는 아이디와 같을 수 없습니다.")
        new_hash = await run_in_threadpool(hash_password, data.new_password)
        # 현재 비밀번호 틀림도 로그인과 같은 DB 카운터로 센다: 훔친 세션으로 현재 비밀번호를 맞혀 보면 5번째에 로그인이 잠긴다.
        # 채널도 로그인과 같다: 요청의 기기 쿠키가 이 사용자의 등록 기기면 등록 기기 카운터, 아니면 새 기기 카운터
        # (훔친 세션만 가진 공격자는 기기 쿠키가 없어 새 기기 채널을 소진한다 — 주인의 등록 기기 로그인은 영향 없음).
        # 위의 규칙 위반(같은 비밀번호 등)은 비밀번호를 검증하지 않았으므로 세지 않는다. 선증가는 로그인처럼 먼저 커밋한다
        async with db.begin():
            device = await self._is_registered_device(db, current_user.user_id, raw_device_token)
            count = await user_repository.count_login_attempt(db, current_user.user_id, MAX_LOGIN_FAILURES, device)
            locked = count is None and (await user_repository.find_by_id(db, current_user.user_id)).login_locked(device)
        if count is None:
            raise _locked() if locked else _busy()
        wrong = False
        async with db.begin():
            # 먼저 잠그고 잠근 뒤 검사한다: 비밀번호 확인도 잠근 시점 값으로, 그리고 다른 기기가 지금 갱신 중이어도
            # 그 새 행까지 폐기되게 한다(lock_user 설명)
            user = await user_repository.lock_user(db, current_user.user_id)
            if user is None:
                raise UnauthorizedException(
                    message="유효하지 않거나 만료된 토큰입니다.", code="INVALID_TOKEN"
                )
            if user.login_locked(device):
                raise _locked()
            if not await run_in_threadpool(verify_password, data.current_password, user.hashed_password):
                # 잠금을 커밋해야 하므로 여기서 raise하지 않는다(raise하면 begin()이 롤백한다). 블록 밖에서 알린다
                if count >= MAX_LOGIN_FAILURES:
                    await user_repository.lock_login(db, user.user_id, datetime.now(timezone.utc), MAX_LOGIN_FAILURES, device)
                wrong = True
            else:
                user.hashed_password = new_hash
                user.reset_login_failures(device)
                # 비밀번호를 바꾸는 흔한 이유가 "누가 내 계정에 들어온 것 같다"이므로 모든 기기의 세션을 끊고,
                # 지금 이 기기만 새 세션으로 이어 준다. (다른 기기의 액세스 토큰도 다음 요청부터 바로 거절된다, C-087)
                # 등록 기기는 유지한다: 본인이 현재 비밀번호를 알고 바꾸는 것이다(재설정과 다름, reset_password)
                now = datetime.now(timezone.utc)
                await user_repository.revoke_user_refresh_tokens(db, user.user_id, now, "PASSWORD_CHANGED")
                _, session = await self._issue_tokens(db, user.user_id, str(uuid.uuid4()), now)
        if wrong:
            if count >= MAX_LOGIN_FAILURES:
                raise _locked()
            raise BadRequestException(code="INVALID_CURRENT_PASSWORD", message="현재 비밀번호가 올바르지 않습니다.")
        return session

    async def list_devices(
        self, db: AsyncSession, current_user: UserResponse, raw_device_token: str | None
    ) -> list[tuple[UserDevice, bool]]:
        """해제되지 않은 내 기기와 '현재 기기인가'(요청의 기기 쿠키가 그 기기)."""
        current_hash = hash_refresh_token(raw_device_token) if raw_device_token else None
        async with db.begin():
            rows = await user_repository.list_active_devices(db, current_user.user_id)
        return [(row, row.token_hash == current_hash) for row in rows]

    async def revoke_device(
        self, db: AsyncSession, current_user: UserResponse, device_id: int, raw_device_token: str | None
    ) -> bool:
        """내 기기 하나를 해제하고 '지금 이 기기였는가'를 돌려준다(라우터가 쿠키를 지운다). 남의 기기·없는 기기·이미 해제는 404.

        세션은 끊지 않는다: 해제는 '이 기기는 다음 로그인부터 휴대폰 인증을 다시 하라'는 뜻이다.
        """
        async with db.begin():
            token_hash = await user_repository.revoke_device(db, current_user.user_id, device_id, datetime.now(timezone.utc))
        if token_hash is None:
            raise NotFoundException(message="등록된 기기를 찾을 수 없습니다.", code="DEVICE_NOT_FOUND")
        return bool(raw_device_token) and token_hash == hash_refresh_token(raw_device_token)


user_service = UserService()
