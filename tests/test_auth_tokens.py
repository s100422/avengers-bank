"""짧은 액세스 토큰 + 갱신 토큰(회전·재사용 감지·로그아웃·비밀번호 변경 시 세션 폐기)."""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select, update

from avengers_bank.core.config import Settings, get_settings
from avengers_bank.core.database import SessionLocal
from avengers_bank.core.security import create_access_token, hash_refresh_token, new_refresh_token
from avengers_bank.domains.users.models import RefreshToken
from tests.cookie_helpers import cookie_header, cookie_value, logout, refresh, session_of, set_cookies

pytestmark = pytest.mark.anyio

LOGIN_ID = "token_user1"
PASSWORD = "Passw0rd!23"
NEW_PASSWORD = "N3w-Passw0rd!"


async def signup(client):
    body = {"login_id": LOGIN_ID, "password": PASSWORD, "name": "토니", "phone": "010-1234-5678"}
    assert (await client.post("/users/signup", json=body)).status_code == 201


async def login(client, password=PASSWORD) -> dict:
    response = await client.post("/users/login", json={"login_id": LOGIN_ID, "password": password})
    assert response.status_code == 200, response.text
    return session_of(response)


def bearer(tokens) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def error_of(response):
    return response.status_code, response.json()["error"]["code"]


async def add_other_device(tokens) -> dict:
    """같은 사용자의 '다른 기기 세션'을 DB에 직접 만든다.

    로그인 API로 만들면 단일 세션 정책 때문에 기존 세션(tokens)이 끊긴다. 여러 세션이 함께 살아 있는 상황
    (정책 도입 전에 만들어진 세션 등)에서 폐기 범위를 확인하는 테스트가 쓴다.
    """
    async with SessionLocal() as db, db.begin():
        mine = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(tokens["refresh_token"])))
        raw, family = new_refresh_token(), str(uuid.uuid4())
        db.add(RefreshToken(
            user_id=mine.user_id, family_id=family, token_hash=hash_refresh_token(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        ))
    return {"refresh_token": raw, "access_token": create_access_token(mine.user_id, family)}


@pytest.fixture
async def tokens(client):
    await signup(client)
    return await login(client)


async def test_login_returns_access_and_refresh_tokens(client):
    await signup(client)
    response = await client.post("/users/login", json={"login_id": LOGIN_ID, "password": PASSWORD})
    data = response.json()["data"]
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 300
    assert data["status"] == "OK"
    assert data["access_token"] and "refresh_token" not in data  # 갱신 토큰은 본문에 없다(쿠키로만)
    assert cookie_value(response)
    session_expires_at = datetime.fromisoformat(data["session_expires_at"])
    remaining = session_expires_at - datetime.now(timezone.utc)
    assert timedelta(minutes=29) < remaining <= timedelta(minutes=30)
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"
    assert (await client.get("/users/me", headers=bearer(data))).status_code == 200


async def test_access_token_lives_five_minutes(tokens):
    payload = jwt.decode(tokens["access_token"], options={"verify_signature": False})
    assert payload["exp"] - payload["iat"] == 300


async def test_only_hash_is_stored(tokens):
    async with SessionLocal() as db:
        rows = (await db.scalars(select(RefreshToken))).all()
    assert len(rows) == 1
    assert rows[0].token_hash == hash_refresh_token(tokens["refresh_token"])
    assert tokens["refresh_token"] not in rows[0].token_hash


async def test_refresh_rotates_tokens(client, tokens):
    response = await refresh(client, tokens["refresh_token"])
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    new = session_of(response)
    assert new["refresh_token"] != tokens["refresh_token"]
    assert new["expires_in"] == 300
    assert (await client.get("/users/me", headers=bearer(new))).status_code == 200
    # 새 토큰으로 또 갱신할 수 있다 (같은 family로 이어진다)
    newer = await refresh(client, new["refresh_token"])
    assert newer.status_code == 200
    async with SessionLocal() as db:
        families = set((await db.scalars(select(RefreshToken.family_id))).all())
    assert len(families) == 1


async def test_reused_refresh_token_revokes_whole_family(client, tokens):
    new = session_of(await refresh(client, tokens["refresh_token"]))
    # 이미 교체된 토큰을 다시 낸다 → 탈취로 보고 family 전체 폐기
    assert error_of(await refresh(client, tokens["refresh_token"])) == (401, "REFRESH_TOKEN_REUSED")
    assert error_of(await refresh(client, new["refresh_token"])) == (401, "INVALID_REFRESH_TOKEN")


async def test_reuse_does_not_touch_other_sessions(client, tokens):
    other = await add_other_device(tokens)
    await refresh(client, tokens["refresh_token"])
    await refresh(client, tokens["refresh_token"])  # 재사용 → 이 세션만 끊긴다
    assert (await refresh(client, other["refresh_token"])).status_code == 200


async def test_unknown_refresh_token(client, tokens):
    response = await refresh(client, "not-a-real-token")
    assert error_of(response) == (401, "INVALID_REFRESH_TOKEN")
    assert response.json()["error"]["message"] == "로그인이 만료되었습니다. 다시 로그인해 주세요."


async def test_expired_refresh_token(client, tokens):
    async with SessionLocal() as db, db.begin():
        await db.execute(update(RefreshToken).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    assert error_of(await refresh(client, tokens["refresh_token"])) == (401, "INVALID_REFRESH_TOKEN")


async def test_logout_revokes_session_and_is_idempotent(client, tokens):
    new = session_of(await refresh(client, tokens["refresh_token"]))
    response = await logout(client, new["refresh_token"])
    assert response.status_code == 200
    assert error_of(await refresh(client, new["refresh_token"])) == (401, "INVALID_REFRESH_TOKEN")
    # 같은 토큰으로 다시, 모르는 토큰으로도 200
    assert (await logout(client, new["refresh_token"])).status_code == 200
    assert (await logout(client, "unknown")).status_code == 200
    assert (await client.post("/users/logout", headers={"Cookie": ""})).status_code == 200  # 쿠키가 아예 없어도


async def me_status(client, session) -> int:
    return (await client.get("/users/me", headers=bearer(session))).status_code


async def test_access_token_carries_session_id(tokens):
    payload = jwt.decode(tokens["access_token"], options={"verify_signature": False})
    async with SessionLocal() as db:
        row = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(tokens["refresh_token"])))
    assert payload["sid"] == row.family_id


async def test_logout_cuts_access_token_immediately(client, tokens):
    """C-087: 로그아웃하면 5분이 남은 액세스 토큰도 다음 요청부터 401. 다른 세션은 그대로."""
    other = await add_other_device(tokens)
    assert await me_status(client, tokens) == 200
    await logout(client, tokens["refresh_token"])
    assert await me_status(client, tokens) == 401
    assert await me_status(client, other) == 200


async def test_session_survives_rotation(client, tokens):
    """갱신(회전)해도 세션은 같으므로, 갱신 전에 받은 액세스 토큰도 만료 전까지는 그대로 쓸 수 있다."""
    new = session_of(await refresh(client, tokens["refresh_token"]))
    assert await me_status(client, tokens) == 200
    assert await me_status(client, new) == 200


async def test_logout_all_and_password_change_cut_other_devices_immediately(client, tokens):
    other = await add_other_device(tokens)
    await client.post("/users/logout-all", headers=bearer(tokens))
    assert (await me_status(client, tokens), await me_status(client, other)) == (401, 401)

    first = await login(client)
    second = await add_other_device(first)
    body = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    fresh = session_of(await client.patch("/users/me/password", json=body, headers=bearer(first)))
    assert (await me_status(client, first), await me_status(client, second)) == (401, 401)
    assert await me_status(client, fresh) == 200  # 비밀번호를 바꾼 이 기기의 새 세션은 동작


async def test_reuse_detection_cuts_access_token_immediately(client, tokens):
    await refresh(client, tokens["refresh_token"])
    await refresh(client, tokens["refresh_token"])  # 이미 교체된 토큰 재사용 → 세션 전체 폐기
    assert await me_status(client, tokens) == 401


async def test_logout_all_revokes_every_session_and_needs_login(client, tokens):
    other = await add_other_device(tokens)  # 다른 기기의 세션
    assert (await client.post("/users/logout-all")).status_code == 401  # 액세스 토큰 없이는 못 끊는다
    response = await client.post("/users/logout-all", headers=bearer(tokens))
    assert (response.status_code, response.json()["message"]) == (200, "모든 기기에서 로그아웃되었습니다.")
    for session in (tokens, other):  # 이 기기와 다른 기기 모두 끊겼다
        assert error_of(await refresh(client, session["refresh_token"])) == (401, "INVALID_REFRESH_TOKEN")
    assert (await login(client))["refresh_token"]  # 다시 로그인하면 새 세션


async def test_password_change_revokes_all_sessions_and_issues_new_one(client, tokens):
    other = await add_other_device(tokens)
    body = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    response = await client.patch("/users/me/password", json=body, headers=bearer(tokens))
    assert response.status_code == 200
    assert response.json()["message"] == "비밀번호가 변경되었습니다."
    assert response.headers["Cache-Control"] == "no-store"
    fresh = session_of(response)
    for old in (tokens, other):
        assert error_of(await refresh(client, old["refresh_token"])) == (401, "INVALID_REFRESH_TOKEN")
    assert (await client.get("/users/me", headers=bearer(fresh))).status_code == 200
    assert (await refresh(client, fresh["refresh_token"])).status_code == 200
    await login(client, NEW_PASSWORD)


async def test_new_password_same_as_login_id(client, tokens):
    body = {"current_password": PASSWORD, "new_password": LOGIN_ID.upper()}
    response = await client.patch("/users/me/password", json=body, headers=bearer(tokens))
    assert error_of(response) == (400, "PASSWORD_SAME_AS_LOGIN_ID")
    assert (await refresh(client, tokens["refresh_token"])).status_code == 200  # 세션은 그대로


# --- 쿠키 전환: 갱신 토큰은 httpOnly 쿠키로만 오간다 ---


async def test_login_cookie_attributes(client):
    await signup(client)
    response = await client.post("/users/login", json={"login_id": LOGIN_ID, "password": PASSWORD})
    morsel = set_cookies(response)["refresh_token"]
    assert morsel["httponly"] is True
    assert morsel["samesite"].lower() == "strict"
    assert morsel["path"] == get_settings().refresh_cookie_path
    assert int(morsel["max-age"]) == 30 * 60
    assert not morsel["secure"]  # 테스트 환경은 COOKIE_SECURE=false (아래 테스트가 Secure를 확인)


async def test_cookie_defaults_and_secure_flag(client, monkeypatch):
    fields = Settings.model_fields
    assert (fields["cookie_secure"].default, fields["refresh_cookie_path"].default) == (True, "/api/users")
    monkeypatch.setattr(get_settings(), "cookie_secure", True)
    await signup(client)
    response = await client.post("/users/login", json={"login_id": LOGIN_ID, "password": PASSWORD})
    assert set_cookies(response)["refresh_token"]["secure"] is True


async def test_refresh_sets_new_cookie_and_body_has_no_token(client, tokens):
    response = await refresh(client, tokens["refresh_token"])
    assert "refresh_token" not in response.json()["data"]
    assert cookie_value(response) not in (None, tokens["refresh_token"])
    assert set_cookies(response)["refresh_token"]["httponly"] is True


async def test_refresh_uses_cookie_jar_without_body(client, tokens):
    """브라우저처럼: 로그인 때 받은 쿠키를 보관함이 알아서 실어 보낸다."""
    assert (await client.post("/users/token/refresh")).status_code == 200
    assert (await client.post("/users/token/refresh")).status_code == 200  # 회전된 새 쿠키로 이어진다


async def test_refresh_without_cookie_is_401(client):
    response = await client.post("/users/token/refresh")
    assert error_of(response) == (401, "INVALID_REFRESH_TOKEN")


async def test_refresh_and_logout_reject_wrong_or_missing_origin(client, tokens):
    for origin in ("http://evil.example", ""):  # 다른 사이트 / Origin 없음
        for path in ("/users/token/refresh", "/users/logout"):
            response = await client.post(path, headers={"Origin": origin, **cookie_header(tokens["refresh_token"])})
            assert error_of(response) == (403, "CSRF_ORIGIN"), (path, origin)
    # 거절된 요청은 세션을 건드리지 않았다
    assert (await refresh(client, tokens["refresh_token"])).status_code == 200


async def test_logout_clears_cookie(client, tokens):
    response = await client.post("/users/logout")
    morsel = set_cookies(response)["refresh_token"]
    assert morsel.value == "" and int(morsel["max-age"]) == 0
    assert morsel["path"] == get_settings().refresh_cookie_path
    assert (await client.post("/users/token/refresh")).status_code == 401  # 보관함에서도 사라졌다


async def test_dead_session_refresh_clears_cookie(client, tokens):
    await logout(client, tokens["refresh_token"])
    response = await refresh(client, tokens["refresh_token"])
    assert error_of(response) == (401, "INVALID_REFRESH_TOKEN")
    assert int(set_cookies(response)["refresh_token"]["max-age"]) == 0


async def test_reused_token_refresh_clears_cookie_and_still_revokes(client, tokens):
    await refresh(client, tokens["refresh_token"])
    response = await refresh(client, tokens["refresh_token"])
    assert error_of(response) == (401, "REFRESH_TOKEN_REUSED")
    assert int(set_cookies(response)["refresh_token"]["max-age"]) == 0
    async with SessionLocal() as db:  # 401을 던지기 전에 폐기가 커밋됐다
        assert (await db.scalar(select(RefreshToken).where(RefreshToken.revoked_at.is_(None)))) is None


async def test_unknown_token_refresh_clears_cookie(client, tokens):
    response = await refresh(client, "not-a-real-token")
    assert int(set_cookies(response)["refresh_token"]["max-age"]) == 0


async def test_password_change_sets_cookie(client, tokens):
    body = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    response = await client.patch("/users/me/password", json=body, headers=bearer(tokens))
    assert "refresh_token" not in response.json()["data"]
    assert cookie_value(response) not in (None, tokens["refresh_token"])
