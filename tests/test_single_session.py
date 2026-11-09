"""단일 세션: 다른 곳에서 로그인하면 기존 세션을 끊는다. 폐기 이유(revoked_reason)가 경로마다 맞게 남는다.

동시 로그인·갱신 경쟁(users 행 잠금)은 SQLite가 FOR UPDATE를 무시해 여기서 볼 수 없다
→ scripts/pg_single_session_concurrency.py.
"""

import pytest
from sqlalchemy import select

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.security import hash_refresh_token
from avengers_bank.domains.users.models import RefreshToken
from tests.cookie_helpers import logout, session_of
from tests.test_auth_tokens import (
    LOGIN_ID,
    NEW_PASSWORD,
    PASSWORD,
    add_other_device,
    bearer,
    error_of,
    login,
    me_status,
    refresh,
    signup,
)

pytestmark = pytest.mark.anyio


async def reason_of(session) -> str | None:
    async with SessionLocal() as db:
        return await db.scalar(
            select(RefreshToken.revoked_reason).where(RefreshToken.token_hash == hash_refresh_token(session["refresh_token"]))
        )


async def alive_families() -> set[str]:
    async with SessionLocal() as db:
        return set((await db.scalars(select(RefreshToken.family_id).where(RefreshToken.revoked_at.is_(None)))).all())


async def test_login_elsewhere_ends_previous_session(client):
    await signup(client)
    first = await login(client)
    second = await login(client)  # 다른 곳에서 로그인

    response = await refresh(client, first["refresh_token"])
    assert error_of(response) == (401, "SESSION_REPLACED")
    assert response.json()["error"]["message"] == "다른 곳에서 로그인되어 로그아웃되었습니다."
    assert await me_status(client, first) == 401  # 액세스 토큰도 다음 요청부터 바로 거절 (C-087)

    assert await me_status(client, second) == 200
    assert (await refresh(client, second["refresh_token"])).status_code == 200
    assert len(await alive_families()) == 1


async def test_rotated_session_is_also_replaced(client):
    """갱신을 몇 번 한 세션도, 마지막 토큰으로 갱신하면 SESSION_REPLACED."""
    await signup(client)
    first = await login(client)
    latest = session_of(await refresh(client, first["refresh_token"]))
    await login(client)
    assert error_of(await refresh(client, latest["refresh_token"])) == (401, "SESSION_REPLACED")
    # 이미 교체된 옛 토큰은 여전히 재사용 감지로 처리된다 (흐름 변경 없음)
    assert error_of(await refresh(client, first["refresh_token"])) == (401, "REFRESH_TOKEN_REUSED")


async def test_other_users_sessions_are_untouched(client, make_user):
    other_headers = await make_user("hulk_user")
    await signup(client)
    await login(client)
    await login(client)
    assert (await client.get("/users/me", headers=other_headers)).status_code == 200


async def test_signup_issues_no_session_and_login_after_signup_is_single(client):
    """가입은 토큰을 주지 않는다. 가입 직후 자동 로그인은 그냥 로그인 API라 별도 처리가 필요 없다."""
    await signup(client)
    assert await alive_families() == set()
    await login(client)
    assert len(await alive_families()) == 1


async def test_revoked_reason_for_each_path(client):
    await signup(client)
    a = await login(client)

    rotated = session_of(await refresh(client, a["refresh_token"]))
    assert await reason_of(a) == "ROTATED"

    await logout(client, rotated["refresh_token"])
    assert await reason_of(rotated) == "LOGOUT"

    b = await login(client)
    await client.post("/users/logout-all", headers=bearer(b))
    assert await reason_of(b) == "LOGOUT_ALL"

    c = await login(client)
    other = await add_other_device(c)
    body = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    fresh = session_of(await client.patch("/users/me/password", json=body, headers=bearer(c)))
    assert (await reason_of(c), await reason_of(other)) == ("PASSWORD_CHANGED", "PASSWORD_CHANGED")

    newer = session_of(await refresh(client, fresh["refresh_token"]))
    await refresh(client, fresh["refresh_token"])  # 이미 교체된 토큰 재사용
    assert (await reason_of(fresh), await reason_of(newer)) == ("ROTATED", "REUSE_DETECTED")

    d = session_of(await client.post("/users/login", json={"login_id": LOGIN_ID, "password": NEW_PASSWORD}))
    await client.post("/users/login", json={"login_id": LOGIN_ID, "password": NEW_PASSWORD})
    assert await reason_of(d) == "LOGIN_ELSEWHERE"
    # 이미 끊긴 행의 이유는 다음 로그인이 덮어쓰지 않는다
    assert (await reason_of(rotated), await reason_of(b)) == ("LOGOUT", "LOGOUT_ALL")


async def test_logout_and_password_change_are_not_session_replaced(client):
    await signup(client)
    a = await login(client)
    await logout(client, a["refresh_token"])
    assert error_of(await refresh(client, a["refresh_token"])) == (401, "INVALID_REFRESH_TOKEN")

    b = await login(client)
    other = await add_other_device(b)
    body = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    await client.patch("/users/me/password", json=body, headers=bearer(b))
    for old in (b, other):
        assert error_of(await refresh(client, old["refresh_token"])) == (401, "INVALID_REFRESH_TOKEN")
