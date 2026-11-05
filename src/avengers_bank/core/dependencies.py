from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.exceptions import UnauthorizedException
from avengers_bank.domains.users.schemas import UserResponse
from avengers_bank.domains.users.service import user_service

bearer_scheme = HTTPBearer(bearerFormat="JWT", auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> UserResponse:
    if credentials is None:
        raise UnauthorizedException(
            message="로그인이 필요합니다.", code="AUTHENTICATION_REQUIRED"
        )
    # get_db를 쓰지 않고 세션을 따로 연다. 같은 세션을 쓰면 여기서 한 조회가 트랜잭션을
    # 자동으로 시작해서, 이후 service의 `async with db.begin():`이 "이미 시작됨" 오류를 낸다.
    # 이 세션은 블록이 끝날 때 커넥션을 반납하므로 커넥션 두 개를 동시에 쓰지는 않는다.
    async with SessionLocal() as db:
        user = await user_service.get_current_user(db, credentials.credentials)
        return UserResponse.model_validate(user)
