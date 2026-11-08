import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import (
    ApiException,
    BadRequestException,
    ConflictException,
    ForbiddenException,
    UnauthorizedException,
)
from avengers_bank.core.security import (
    DUMMY_HASH,
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from avengers_bank.domains.users.models import RefreshToken, User
from avengers_bank.domains.users.repository import user_repository
from avengers_bank.domains.users.schemas import (
    PasswordChange,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
)
from avengers_bank.domains.verification.service import consume_verification

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


class UserService:
    async def _issue_tokens(
        self, db: AsyncSession, user_id: int, family_id: str, now: datetime
    ) -> tuple[RefreshToken, TokenResponse]:
        """새 액세스 토큰 + 새 갱신 토큰. 갱신 토큰은 해시만 저장하고 원문은 응답으로 한 번만 내보낸다."""
        settings = get_settings()
        raw = new_refresh_token()
        # 슬라이딩 세션: 갱신할 때마다 '지금부터 30분'으로 새로 잡는다. 30분 동안 갱신이 없으면 끝
        expires_at = now + timedelta(minutes=settings.session_expire_minutes)
        row = await user_repository.save_refresh_token(
            db, RefreshToken(user_id=user_id, family_id=family_id, token_hash=hash_refresh_token(raw), expires_at=expires_at)
        )
        return row, TokenResponse(
            access_token=create_access_token(user_id, family_id),
            refresh_token=raw,
            expires_in=settings.access_token_expire_minutes * 60,
            session_expires_at=expires_at,
        )

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

    async def login(self, db: AsyncSession, data: UserLogin) -> TokenResponse:
        """은행식 로그인 잠금 (C-090): 같은 아이디로 5회 연속 틀리면 잠그고, 잠기면 맞는 비밀번호도 거절한다.

        순서: 아이디 조회 → 잠겼으면 403 → 실패 1회를 *먼저* 센다(커밋) → 비밀번호 검증 → 맞으면 0으로, 5번째로 틀리면 잠금.
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
            if user is not None and user.login_locked_at is None:
                count = await user_repository.count_login_attempt(db, user.user_id, MAX_LOGIN_FAILURES)
        if user is None:
            # 없는 아이디도 가짜 해시로 검증해서 응답 시간으로 아이디 존재를 알 수 없게 한다. 행이 없으니 잠금도 없다(IP 한도만)
            await run_in_threadpool(verify_password, data.password, DUMMY_HASH)
            raise invalid
        if count is None:
            # 검증하지 않는다. 이미 잠겼으면 403, 아니면 동시에 온 요청들이 5번을 다 가져간 것이라 429
            raise _locked() if user.login_locked_at is not None else _busy()

        # 2) 검증은 트랜잭션·행 잠금 밖에서 한다(약 70ms): 틀린 비밀번호 요청이 사용자 행을 붙잡지 않게
        if not await run_in_threadpool(verify_password, data.password, user.hashed_password):
            if count >= MAX_LOGIN_FAILURES:
                async with db.begin():  # 잠금도 커밋한 뒤에 알린다
                    await user_repository.lock_login(db, user.user_id, datetime.now(timezone.utc), MAX_LOGIN_FAILURES)
                raise _locked()
            raise invalid

        # 3) 성공. 단일 세션: 다른 곳에서 로그인하면 기존 세션을 모두 끊는다. 잠그지 않으면 동시 로그인 두 개가
        #    서로의 커밋 전 새 행을 못 봐 둘 다 살아남는다(lock_user 설명). 끊긴 기기의 액세스 토큰도 다음 요청부터 401(C-087)
        async with db.begin():
            user = await user_repository.lock_user(db, user.user_id)
            if user is None:
                raise invalid
            if user.login_locked_at is not None:
                raise _locked()  # 검증하는 사이에 다른 요청의 5번째 실패로 잠겼다: 잠기면 맞는 비밀번호도 거절
            user.failed_login_count = 0  # '연속' 실패만 센다
            now = datetime.now(timezone.utc)
            await user_repository.revoke_user_refresh_tokens(db, user.user_id, now, LOGIN_ELSEWHERE)
            # 로그인 1번 = 새 family(세션) 1개. 이후 갱신 토큰은 이 family 안에서 이어진다
            _, tokens = await self._issue_tokens(db, user.user_id, str(uuid.uuid4()), now)
        return tokens

    async def refresh(self, db: AsyncSession, raw_token: str) -> TokenResponse:
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
                new_row, tokens = await self._issue_tokens(db, token.user_id, token.family_id, now)
                token.revoked_at = now
                token.revoked_reason = "ROTATED"
                token.replaced_by_id = new_row.refresh_token_id
        if reused:
            raise UnauthorizedException(message=SESSION_EXPIRED_MESSAGE, code="REFRESH_TOKEN_REUSED")
        return tokens

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
            changes = data.model_dump(exclude_unset=True)
            token = changes.pop("phone_verification_token", None)
            if "phone" in changes and changes["phone"] != user.phone:
                # 휴대폰 번호는 본인 확인·알림·2단계 비밀번호 찾기에 쓰이므로 새 번호로 받은 인증번호를 확인해야 바꾼다
                if token is None:
                    raise BadRequestException(
                        code="PHONE_VERIFICATION_REQUIRED", message="휴대폰 번호를 바꾸려면 새 번호로 인증해 주세요."
                    )
                await consume_verification(db, token, "CHANGE_PHONE", phone=changes["phone"], user_id=user.user_id)
                user.phone_verified_at = datetime.now(timezone.utc)
            for field, value in changes.items():
                setattr(user, field, value)
        return user

    async def unlock_login(self, db: AsyncSession, login_id: str) -> bool:
        """로그인 잠금 해제 + 실패 횟수 0. 개발용 API·관리자 명령이 쓴다(2단계: 비밀번호 찾기). 없는 아이디면 False."""
        async with db.begin():
            return await user_repository.unlock_login(db, login_id)

    async def reset_password(self, db: AsyncSession, login_id: str, new_password: str) -> bool:
        """새 비밀번호로 바꾸고, 잠금을 풀고, 모든 세션을 끊는다(관리자 명령, 2단계 비밀번호 찾기). 없는 아이디면 False.

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
            await user_repository.revoke_user_refresh_tokens(
                db, user.user_id, datetime.now(timezone.utc), "PASSWORD_CHANGED"
            )
        return True

    async def change_password(
        self, db: AsyncSession, current_user: UserResponse, data: PasswordChange
    ) -> TokenResponse:
        if data.new_password == data.current_password:
            raise BadRequestException(code="SAME_PASSWORD", message="새 비밀번호가 현재 비밀번호와 같습니다.")
        # 강도 규칙은 PasswordChange 스키마가 본다. 아이디는 스키마가 모르므로 여기서 비교한다(가입과 같게 대소문자 무시)
        if data.new_password.lower() == current_user.login_id.lower():
            raise BadRequestException(code="PASSWORD_SAME_AS_LOGIN_ID", message="비밀번호는 아이디와 같을 수 없습니다.")
        new_hash = await run_in_threadpool(hash_password, data.new_password)
        # 현재 비밀번호 틀림도 로그인과 같은 DB 카운터로 센다: 훔친 세션으로 현재 비밀번호를 맞혀 보면 5번째에 로그인이 잠긴다.
        # 위의 규칙 위반(같은 비밀번호 등)은 비밀번호를 검증하지 않았으므로 세지 않는다. 선증가는 로그인처럼 먼저 커밋한다
        async with db.begin():
            count = await user_repository.count_login_attempt(db, current_user.user_id, MAX_LOGIN_FAILURES)
            locked = count is None and (await user_repository.find_by_id(db, current_user.user_id)).login_locked_at is not None
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
            if user.login_locked_at is not None:
                raise _locked()
            if not await run_in_threadpool(verify_password, data.current_password, user.hashed_password):
                # 잠금을 커밋해야 하므로 여기서 raise하지 않는다(raise하면 begin()이 롤백한다). 블록 밖에서 알린다
                if count >= MAX_LOGIN_FAILURES:
                    await user_repository.lock_login(db, user.user_id, datetime.now(timezone.utc), MAX_LOGIN_FAILURES)
                wrong = True
            else:
                user.hashed_password = new_hash
                user.failed_login_count = 0
                # 비밀번호를 바꾸는 흔한 이유가 "누가 내 계정에 들어온 것 같다"이므로 모든 기기의 세션을 끊고,
                # 지금 이 기기만 새 세션으로 이어 준다. (다른 기기의 액세스 토큰도 다음 요청부터 바로 거절된다, C-087)
                now = datetime.now(timezone.utc)
                await user_repository.revoke_user_refresh_tokens(db, user.user_id, now, "PASSWORD_CHANGED")
                _, tokens = await self._issue_tokens(db, user.user_id, str(uuid.uuid4()), now)
        if wrong:
            if count >= MAX_LOGIN_FAILURES:
                raise _locked()
            raise BadRequestException(code="INVALID_CURRENT_PASSWORD", message="현재 비밀번호가 올바르지 않습니다.")
        return tokens


user_service = UserService()
