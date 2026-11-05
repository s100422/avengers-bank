from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from avengers_bank.core.exceptions import BadRequestException, ConflictException, UnauthorizedException
from avengers_bank.core.security import (
    DUMMY_HASH,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from avengers_bank.domains.users.models import User
from avengers_bank.domains.users.repository import user_repository
from avengers_bank.domains.users.schemas import (
    PasswordChange,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
)


class UserService:
    async def signup(self, db: AsyncSession, data: UserCreate) -> User:
        hashed_password = await run_in_threadpool(hash_password, data.password)
        duplicate = ConflictException(
            code="LOGIN_ID_ALREADY_EXISTS", message="이미 사용 중인 아이디입니다."
        )

        try:
            async with db.begin():
                if await user_repository.find_by_login_id(db, data.login_id) is not None:
                    raise duplicate
                user = User(
                    login_id=data.login_id,
                    hashed_password=hashed_password,
                    name=data.name,
                    nick_name=data.nick_name,
                    phone=data.phone,
                )
                await user_repository.save(db, user)
                await db.refresh(user)
        except IntegrityError:
            # 동시 가입 요청이 위 조회를 함께 통과하면 DB unique 제약이 최종 판정한다.
            raise duplicate from None

        return user

    async def login(self, db: AsyncSession, data: UserLogin) -> str:
        async with db.begin():
            user = await user_repository.find_by_login_id(db, data.login_id)
            # 없는 아이디도 가짜 해시로 검증해서, 응답 시간으로 아이디 존재를 알 수 없게 한다
            hashed_password = user.hashed_password if user else DUMMY_HASH
            password_ok = await run_in_threadpool(verify_password, data.password, hashed_password)
            if user is None or not password_ok:
                raise UnauthorizedException(
                    message="아이디 또는 비밀번호가 올바르지 않습니다.", code="INVALID_CREDENTIALS"
                )

            user_id = user.user_id

        return create_access_token(user_id)

    async def get_current_user(self, db: AsyncSession, token: str) -> User:
        user_id = decode_access_token(token)
        user = await user_repository.find_by_id(db, user_id)
        if user is None:
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

    async def change_password(self, db: AsyncSession, current_user: UserResponse, data: PasswordChange) -> None:
        if data.new_password == data.current_password:
            raise BadRequestException(code="SAME_PASSWORD", message="새 비밀번호가 현재 비밀번호와 같습니다.")
        new_hash = await run_in_threadpool(hash_password, data.new_password)
        async with db.begin():
            user = await user_repository.find_by_id(db, current_user.user_id)
            if user is None:
                raise UnauthorizedException(
                    message="유효하지 않거나 만료된 토큰입니다.", code="INVALID_TOKEN"
                )
            if not await run_in_threadpool(verify_password, data.current_password, user.hashed_password):
                raise BadRequestException(
                    code="INVALID_CURRENT_PASSWORD", message="현재 비밀번호가 올바르지 않습니다."
                )
            user.hashed_password = new_hash


user_service = UserService()
