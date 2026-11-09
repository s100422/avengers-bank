from datetime import datetime

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.users.models import RefreshToken, User, UserDevice


class UserRepository:
    async def save(self, db: AsyncSession, user: User) -> User:
        db.add(user)
        await db.flush()
        return user

    async def find_by_login_id(self, db: AsyncSession, login_id: str) -> User | None:
        return await db.scalar(select(User).where(User.login_id == login_id))

    async def find_by_id(self, db: AsyncSession, user_id: int) -> User | None:
        return await db.get(User, user_id)

    async def lock_user(self, db: AsyncSession, user_id: int) -> User | None:
        """그 사용자의 '세션 집합'을 바꾸기 전에 users 행을 잠근다. 잠금 순서: users → refresh_tokens.

        왜 토큰 행이 아니라 사용자 행인가: 폐기 UPDATE는 '지금 커밋된 행'만 본다(PostgreSQL READ COMMITTED).
        - 동시 로그인 A·B: 둘 다 "다른 세션 폐기"를 할 때 상대의 새 행은 아직 커밋 전이라 안 보인다 → 두 세션 모두 생존.
        - 기기 1 갱신(새 행 INSERT) 중에 다른 곳 로그인·비밀번호 변경·모든 기기 로그아웃: 폐기가 새 행을 못 봐 기기 1이 생존.
        아직 없는 행은 잠글 수 없으니, 그 사용자의 세션을 바꾸는 작업이 모두 같은 사용자 행을 먼저 잠가 한 줄로 세운다.
        populate_existing: 기다리는 동안 바뀌었을 수 있는 값을 잠근 시점 값으로 다시 읽는다. SQLite는 FOR UPDATE를 무시한다.
        """
        stmt = select(User).where(User.user_id == user_id).with_for_update().execution_options(populate_existing=True)
        return await db.scalar(stmt)

    async def count_login_attempt(
        self, db: AsyncSession, user_id: int, max_failures: int, device: bool = False
    ) -> int | None:
        """비밀번호를 검증하기 *전에* 실패 1회를 먼저 센다. 잠겼거나 이미 max_failures번이 세어졌으면 None(검증하지 않는다).

        '읽고 → 검증하고 → 틀리면 +1 저장'으로 하면, 동시에 온 요청 30개가 모두 같은 옛 값(0)을 읽고 30번 검증된다.
        조건과 증가가 한 UPDATE 문장이라 DB가 그 행을 잠근 채 처리한다: 요청마다 서로 다른 값(1, 2, 3, ...)을 받고,
        5를 받은 요청 뒤로는 조건(< 5)이 안 맞아 0행 → None. 서버가 여러 대여도, 재시작해도 정확하다
        (예전 메모리 한도 C-082를 DB로 옮긴 것).

        device: 어느 채널의 카운터인가(False=새 기기, True=등록 기기). 두 채널은 컬럼만 다르고 방식은 같다.
        """
        count, locked = _channel(device)
        stmt = (
            update(User)
            .where(User.user_id == user_id, locked.is_(None), count < max_failures)
            .values({count.key: count + 1})
            .returning(count)
            .execution_options(synchronize_session=False)
        )
        return await db.scalar(stmt)

    async def lock_login(
        self, db: AsyncSession, user_id: int, now: datetime, max_failures: int, device: bool = False
    ) -> None:
        # 카운트 조건: 그사이 맞는 비밀번호로 성공해 0이 됐으면 잠그지 않는다
        count, locked = _channel(device)
        await db.execute(
            update(User)
            .where(User.user_id == user_id, locked.is_(None), count >= max_failures)
            .values({locked.key: now})
            .execution_options(synchronize_session=False)
        )

    async def unlock_login(self, db: AsyncSession, login_id: str) -> bool:
        """두 채널 모두 잠금 해제 + 실패 횟수 0. 그 아이디가 없으면 False."""
        result = await db.execute(
            update(User)
            .where(User.login_id == login_id, User.deleted_at.is_(None))  # 탈퇴 회원은 없는 아이디로 본다
            .values(failed_login_count=0, login_locked_at=None, device_failed_login_count=0, device_login_locked_at=None)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount > 0

    async def find_active_device(self, db: AsyncSession, user_id: int, token_hash: str) -> UserDevice | None:
        """이 사용자의 해제되지 않은 기기 중 쿠키 해시가 맞는 것. 다른 사용자의 기기 쿠키는 '없음'(= 새 기기)."""
        return await db.scalar(
            select(UserDevice).where(
                UserDevice.user_id == user_id, UserDevice.token_hash == token_hash, UserDevice.revoked_at.is_(None)
            )
        )

    async def list_active_devices(self, db: AsyncSession, user_id: int) -> list[UserDevice]:
        rows = await db.scalars(
            select(UserDevice)
            .where(UserDevice.user_id == user_id, UserDevice.revoked_at.is_(None))
            .order_by(UserDevice.last_used_at.desc(), UserDevice.device_id.desc())
        )
        return list(rows)

    async def revoke_device(self, db: AsyncSession, user_id: int, device_id: int, now: datetime) -> str | None:
        """내 기기 하나를 해제하고 그 기기의 token_hash를 돌려준다(현재 기기인지 비교용). 없거나 남의 것·이미 해제면 None."""
        return await db.scalar(
            update(UserDevice)
            .where(UserDevice.device_id == device_id, UserDevice.user_id == user_id, UserDevice.revoked_at.is_(None))
            .values(revoked_at=now)
            .returning(UserDevice.token_hash)
            .execution_options(synchronize_session=False)
        )

    async def revoke_user_devices(self, db: AsyncSession, user_id: int, now: datetime) -> None:
        await db.execute(
            update(UserDevice)
            .where(UserDevice.user_id == user_id, UserDevice.revoked_at.is_(None))
            .values(revoked_at=now)
            .execution_options(synchronize_session=False)
        )

    async def save_refresh_token(self, db: AsyncSession, token: RefreshToken) -> RefreshToken:
        db.add(token)
        await db.flush()  # refresh_token_id를 받아야 이전 토큰의 replaced_by_id에 넣을 수 있다
        return token

    async def find_refresh_token(
        self, db: AsyncSession, token_hash: str, *, for_update: bool = False
    ) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        if for_update:
            # 같은 토큰으로 갱신 요청 두 개가 동시에 오면 둘 다 "아직 유효"로 읽고 각자 새 토큰을 받을 수 있다.
            # 행을 잠그면 두 번째 요청은 첫 번째가 커밋할 때까지 기다렸다가 "이미 교체됨"을 보게 된다 (ERD 규칙 9: 잠근 뒤 검사).
            # populate_existing: 세션에 남은 옛 값이 아니라 잠근 시점의 값을 읽는다. SQLite는 FOR UPDATE를 무시한다.
            # 잠금 순서(users → refresh_tokens): 호출하는 쪽이 lock_user를 먼저 부른 뒤 이것으로 잠근다
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return await db.scalar(stmt)

    async def revoke_refresh_family(self, db: AsyncSession, family_id: str, now: datetime, reason: str) -> None:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason=reason)
        )

    async def is_session_active(self, db: AsyncSession, user_id: int, family_id: str) -> bool:
        """그 세션(family)에 아직 폐기되지 않은 갱신 토큰이 있는가.

        갱신(회전)하면 옛 행은 폐기되지만 새 행이 살아 있으니 세션은 살아 있다. 로그아웃 등으로 family 전체가
        폐기되면 살아 있는 행이 없다. 만료 시각은 보지 않는다: 액세스 토큰(5분)이 갱신 토큰(30분)보다 먼저 만료된다.
        """
        stmt = select(
            exists().where(
                RefreshToken.family_id == family_id,
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
        )
        return bool(await db.scalar(stmt))

    async def revoke_user_refresh_tokens(self, db: AsyncSession, user_id: int, now: datetime, reason: str) -> None:
        """호출하는 쪽이 lock_user로 users 행을 먼저 잠가야 한다(동시에 생기는 새 행까지 끊으려면)."""
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason=reason)
        )


def _channel(device: bool):
    """(실패 횟수 컬럼, 잠긴 시각 컬럼). 새 기기 채널 = 기존 컬럼, 등록 기기 채널 = device_* 컬럼."""
    if device:
        return User.device_failed_login_count, User.device_login_locked_at
    return User.failed_login_count, User.login_locked_at


user_repository = UserRepository()
