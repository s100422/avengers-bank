"""기기 등록(B1): 새 기기 로그인은 휴대폰 인증을 더 하고, 통과한 기기는 쿠키로 기억한다.

로그인 실패는 채널(새 기기 / 등록 기기)마다 따로 센다. BankClient는 평소 새 기기 인증을 자동으로 끝내 주지만(conftest),
여기서는 끄고(auto_device_verification = False) 흐름을 직접 밟는다.
쿠키 보관함이 하나인 client는 '주인의 브라우저'(등록 기기), Cookie 헤더를 비워 보내는 요청은 '쿠키 없는 새 기기'(공격자)다.
PostgreSQL 동시성은 scripts/pg_device_channel_concurrency.py.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from pydantic import SecretStr
from sqlalchemy import select, update

from avengers_bank.core.config import get_settings
from avengers_bank.core.database import SessionLocal
from avengers_bank.core.security import hash_refresh_token
from avengers_bank.domains.users.models import RefreshToken, User, UserDevice
from avengers_bank.domains.users.service import device_label, mask_phone
from avengers_bank.domains.verification.models import VerificationCode
from avengers_bank.domains.verification.sms import dev_inbox
from tests.cookie_helpers import cookie_header, cookie_value, set_cookies
from tests.test_auth_tokens import LOGIN_ID, NEW_PASSWORD, PASSWORD, bearer, error_of, signup
from tests.verification_helpers import auto_device_login, exempt_from_send_limits, read_code

pytestmark = pytest.mark.anyio

WRONG = "Wrong0pass!"
PHONE = "010-1234-5678"
NO_COOKIE = {"Cookie": ""}  # 보관함의 쿠키를 싣지 않는다 = 쿠키 없는 새 기기


@pytest.fixture(autouse=True)
def manual_device_flow(client):
    client.auto_device_verification = False


async def login_raw(client, password=PASSWORD, headers=None, login_id=LOGIN_ID):
    return await client.post("/users/login", json={"login_id": login_id, "password": password}, headers=headers)


async def register(client, password=PASSWORD):
    """로그인 → 새 기기 인증을 끝까지 → 최종 응답. client의 보관함이 이 사용자의 등록 기기가 된다."""
    challenge = (await login_raw(client, password)).json()["data"]["challenge_token"]
    response = await auto_device_login(client, challenge)
    assert response.status_code == 200, response.text
    return response


async def device_rows(user_id: int = 1) -> list[UserDevice]:
    async with SessionLocal() as db:
        return list(await db.scalars(select(UserDevice).where(UserDevice.user_id == user_id).order_by(UserDevice.device_id)))


async def lock_state(device: bool) -> tuple[int, bool]:
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.login_id == LOGIN_ID))
        if device:
            return user.device_failed_login_count, user.device_login_locked_at is not None
        return user.failed_login_count, user.login_locked_at is not None


async def wrong_logins(client, n, headers=None) -> list[int]:
    return [(await login_raw(client, WRONG, headers)).status_code for _ in range(n)]


# ── 새 기기 → 챌린지 ─────────────────────────────────────────────────


async def test_new_device_gets_challenge_not_session(client):
    await signup(client)
    response = await login_raw(client)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "DEVICE_VERIFICATION_REQUIRED"
    assert data["phone_masked"] == "010-****-5678"
    assert set(data) == {"status", "challenge_token", "phone_masked"}  # 액세스 토큰 없음
    payload = jwt.decode(data["challenge_token"], options={"verify_signature": False})
    assert payload["typ"] == "device_challenge" and payload["sub"] == "1"
    assert payload["exp"] - payload["iat"] == 600
    assert set_cookies(response) == {}  # 쿠키도 없음
    async with SessionLocal() as db:
        assert (await db.scalar(select(RefreshToken))) is None  # 세션도 없음
    assert (await device_rows()) == []
    # 챌린지는 액세스 토큰으로 쓸 수 없다
    assert (await client.get("/users/me", headers={"Authorization": f"Bearer {data['challenge_token']}"})).status_code == 401


async def test_mask_phone_and_device_label():
    assert mask_phone("010-1234-5678") == "010-****-5678"
    chrome = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    edge = chrome + " Edg/130.0"
    iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile Safari/604.1"
    assert [device_label(x) for x in (chrome, edge, iphone)] == ["Chrome · Windows", "Edge · Windows", "Safari · iOS"]
    assert device_label(None) == "알 수 없는 브라우저 · 알 수 없는 기기"
    assert len(device_label("Chrome/1 " + "Windows" * 100)) <= 100


# ── 새 기기 인증 → 등록 ──────────────────────────────────────────────


async def test_device_verification_registers_device_and_sets_both_cookies(client):
    await signup(client)
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"}
    challenge = (await login_raw(client)).json()["data"]["challenge_token"]
    client.headers.update(ua)
    response = await auto_device_login(client, challenge)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "OK" and data["access_token"] and "refresh_token" not in data and "device_token" not in data
    assert (await client.get("/users/me", headers=bearer(data))).status_code == 200

    cookies = set_cookies(response)
    assert set(cookies) == {"refresh_token", "device_token"}
    device = cookies["device_token"]
    assert (device["httponly"], device["samesite"].lower(), int(device["max-age"])) == (True, "strict", 365 * 86400)
    assert device["path"] == cookies["refresh_token"]["path"]
    (row,) = await device_rows()
    assert row.token_hash == hash_refresh_token(device.value) and device.value not in row.token_hash  # 해시만 저장
    assert (row.label, row.revoked_at) == ("Chrome · Windows", None)

    # 이제 이 브라우저는 등록 기기: 다음 로그인은 챌린지 없이 바로 세션
    again = await login_raw(client)
    assert again.json()["data"]["status"] == "OK" and cookie_value(again) and "device_token" not in set_cookies(again)


async def test_device_login_keeps_single_session(client):
    await signup(client)
    first = await register(client)
    second = await login_raw(client)  # 등록 기기 로그인
    assert (await client.get("/users/me", headers=bearer(first.json()["data"]))).status_code == 401
    assert (await client.get("/users/me", headers=bearer(second.json()["data"]))).status_code == 200


async def test_registered_login_updates_last_used_and_revoked_cookie_is_new_device(client):
    await signup(client)
    await register(client)
    old = datetime(2020, 1, 1, tzinfo=timezone.utc)
    async with SessionLocal() as db, db.begin():
        await db.execute(update(UserDevice).values(last_used_at=old))
    assert (await login_raw(client)).json()["data"]["status"] == "OK"
    (row,) = await device_rows()
    assert row.last_used_at.replace(tzinfo=timezone.utc) > old + timedelta(days=365)

    async with SessionLocal() as db, db.begin():
        await db.execute(update(UserDevice).values(revoked_at=datetime.now(timezone.utc)))
    assert (await login_raw(client)).json()["data"]["status"] == "DEVICE_VERIFICATION_REQUIRED"  # 해제된 쿠키 = 새 기기
    # 성공하면 낡은 쿠키는 새 것으로 덮어쓴다
    new = await register(client)
    assert cookie_value(new, "device_token")
    assert len(await device_rows()) == 2


async def test_other_users_device_cookie_is_a_new_device(client):
    await signup(client)
    body = {"login_id": "otheruser", "password": PASSWORD, "name": "스티브", "phone": "010-9999-0000"}
    assert (await client.post("/users/signup", json=body)).status_code == 201
    await register(client)  # 이 브라우저는 ironman 소유로 등록
    other = await login_raw(client, login_id="otheruser")
    assert other.json()["data"]["status"] == "DEVICE_VERIFICATION_REQUIRED"


# ── 챌린지·인증 증표의 재사용 ────────────────────────────────────────


async def test_send_goes_to_registered_phone_and_has_send_for_me_shape(client):
    await signup(client)
    challenge = (await login_raw(client)).json()["data"]["challenge_token"]
    response = await client.post("/users/login/device/send", json={"challenge_token": challenge})
    assert response.status_code == 200
    assert set(response.json()["data"]) == {"verification_id", "expires_in"} and response.json()["data"]["expires_in"] == 600
    async with SessionLocal() as db:
        vc = await db.scalar(select(VerificationCode).where(VerificationCode.purpose == "NEW_DEVICE"))
    assert (vc.phone, vc.user_id) == (PHONE, 1)
    assert (await client.post("/users/login/device/send", json={"challenge_token": "garbage"})).status_code == 401
    forged = jwt.encode({"typ": "verification", "sub": "1", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}, "x" * 40, "HS256")
    assert error_of(await client.post("/users/login/device/send", json={"challenge_token": forged})) == (401, "INVALID_DEVICE_CHALLENGE")


async def test_demo_device_code_is_bound_to_configured_account_and_existing_verification_flow(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_device_login_id", LOGIN_ID)
    monkeypatch.setattr(settings, "demo_device_phone", PHONE)
    monkeypatch.setattr(settings, "demo_device_code", SecretStr("483926"))
    monkeypatch.setattr(settings, "demo_device_until", datetime.now(timezone.utc) + timedelta(hours=1))
    await signup(client)
    dev_inbox.clear()

    challenge = (await login_raw(client)).json()["data"]["challenge_token"]
    response = await client.post("/users/login/device/send", json={"challenge_token": challenge})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["delivery"] == "demo" and data["expires_in"] == 600
    assert "483926" not in response.text and response.headers["cache-control"] == "no-store"
    assert not dev_inbox  # 시연 코드는 문자 로그/문자함에도 남기지 않는다
    bad = await client.post("/verification/phone/verify", json={"verification_id": data["verification_id"], "code": "000000"})
    assert error_of(bad) == (400, "INVALID_VERIFICATION_CODE")
    verified = await client.post("/verification/phone/verify", json={"verification_id": data["verification_id"], "code": "483926"})
    assert verified.status_code == 200
    token = verified.json()["data"]["verification_token"]
    registered = await client.post("/users/login/device", json={"challenge_token": challenge, "phone_verification_token": token})
    assert registered.status_code == 200 and registered.json()["data"]["status"] == "OK"

    other_phone = "010-9999-0000"
    assert (await client.post("/users/signup", json={
        "login_id": "otheruser", "password": PASSWORD, "name": "스티브", "phone": other_phone,
    })).status_code == 201
    dev_inbox.clear()
    other_challenge = (await login_raw(client, login_id="otheruser")).json()["data"]["challenge_token"]
    other_send = await client.post("/users/login/device/send", json={"challenge_token": other_challenge})
    assert other_send.status_code == 200 and "delivery" not in other_send.json()["data"]
    assert len(dev_inbox) == 1 and dev_inbox[0][0] == other_phone


async def test_demo_device_code_is_not_used_after_expiry(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "demo_device_login_id", LOGIN_ID)
    monkeypatch.setattr(settings, "demo_device_phone", PHONE)
    monkeypatch.setattr(settings, "demo_device_code", SecretStr("483926"))
    monkeypatch.setattr(settings, "demo_device_until", datetime.now(timezone.utc) - timedelta(seconds=1))
    await signup(client)
    dev_inbox.clear()
    challenge = (await login_raw(client)).json()["data"]["challenge_token"]
    response = await client.post("/users/login/device/send", json={"challenge_token": challenge})
    assert response.status_code == 200 and "delivery" not in response.json()["data"]
    assert len(dev_inbox) == 1  # 시연 기간이 끝나면 원래 발송 경로를 쓴다


async def test_send_respects_existing_send_limit(client):
    await signup(client)
    challenge = (await login_raw(client)).json()["data"]["challenge_token"]
    codes = [(await client.post("/users/login/device/send", json={"challenge_token": challenge})).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]  # 번호당 15분 3번 (가입 때 보낸 인증은 exempt로 빠져 있다)


async def test_verification_token_and_challenge_cannot_be_reused(client):
    await signup(client)
    challenge = (await login_raw(client)).json()["data"]["challenge_token"]
    sent = (await client.post("/users/login/device/send", json={"challenge_token": challenge})).json()["data"]
    await exempt_from_send_limits(sent["verification_id"])
    code = await read_code(client, PHONE)
    token = (await client.post("/verification/phone/verify", json={"verification_id": sent["verification_id"], "code": code})).json()["data"]["verification_token"]
    body = {"challenge_token": challenge, "phone_verification_token": token}
    assert (await client.post("/users/login/device", json=body)).status_code == 200
    # 같은 증표로 한 번 더(같은 챌린지) → 거절, 기기는 하나뿐
    again = await client.post("/users/login/device", json=body, headers=NO_COOKIE)
    assert error_of(again) == (400, "INVALID_VERIFICATION_TOKEN")
    assert len(await device_rows()) == 1
    # 챌린지만 다시 쓰고 인증은 새로 받지 않은 채로는 안 된다. 새로 받으면(전화를 가진 사람) 통과한다
    assert error_of(await client.post("/users/login/device", json={**body, "phone_verification_token": "x"})) == (400, "INVALID_VERIFICATION_TOKEN")


async def test_device_login_rejects_other_purpose_token_and_other_users_token(client):
    await signup(client)
    other = {"login_id": "otheruser", "password": PASSWORD, "name": "스티브", "phone": "010-9999-0000"}
    assert (await client.post("/users/signup", json=other)).status_code == 201
    challenge = (await login_raw(client)).json()["data"]["challenge_token"]
    # 가입용 증표(purpose SIGNUP_PHONE)로는 안 된다
    from tests.verification_helpers import phone_token
    signup_token = await phone_token(client, "010-7777-8888", exempt=True)
    body = {"challenge_token": challenge, "phone_verification_token": signup_token}
    assert error_of(await client.post("/users/login/device", json=body)) == (400, "INVALID_VERIFICATION_TOKEN")
    # 다른 사용자의 새 기기 인증 증표로도 안 된다
    other_challenge = (await login_raw(client, login_id="otheruser")).json()["data"]["challenge_token"]
    sent = (await client.post("/users/login/device/send", json={"challenge_token": other_challenge})).json()["data"]
    await exempt_from_send_limits(sent["verification_id"])
    token = (await client.post("/verification/phone/verify", json={"verification_id": sent["verification_id"], "code": await read_code(client, "010-9999-0000")})).json()["data"]["verification_token"]
    assert error_of(await client.post("/users/login/device", json={"challenge_token": challenge, "phone_verification_token": token})) == (400, "INVALID_VERIFICATION_TOKEN")
    assert await device_rows(1) == []


async def test_expired_challenge_rejected(client):
    await signup(client)
    challenge = (await login_raw(client)).json()["data"]["challenge_token"]
    payload = jwt.decode(challenge, options={"verify_signature": False})
    expired = jwt.encode({**payload, "exp": datetime.now(timezone.utc) - timedelta(seconds=1)}, "test-secret-key-test-secret-key-0000", "HS256")
    assert error_of(await client.post("/users/login/device/send", json={"challenge_token": expired})) == (401, "INVALID_DEVICE_CHALLENGE")


# ── 채널별 실패 횟수·잠금 ────────────────────────────────────────────


async def test_wrong_password_counts_only_on_the_channel_of_the_request(client):
    await signup(client)
    await register(client)
    assert await wrong_logins(client, 2, NO_COOKIE) == [401, 401]
    assert await lock_state(device=False) == (2, False) and await lock_state(device=True) == (0, False)
    assert await wrong_logins(client, 3) == [401, 401, 401]  # 보관함의 기기 쿠키 = 등록 기기 채널
    assert await lock_state(device=False) == (2, False) and await lock_state(device=True) == (3, False)


async def test_locking_new_device_channel_does_not_block_registered_device(client):
    await signup(client)
    await register(client)
    assert await wrong_logins(client, 5, NO_COOKIE) == [401, 401, 401, 401, 403]
    assert error_of(await login_raw(client, headers=NO_COOKIE)) == (403, "ACCOUNT_LOCKED")  # 새 기기는 맞는 비밀번호도 거절
    ok = await login_raw(client)  # 주인의 등록 기기
    assert (ok.status_code, ok.json()["data"]["status"]) == (200, "OK")
    assert await lock_state(device=False) == (5, True) and await lock_state(device=True) == (0, False)


async def test_locking_registered_channel_does_not_block_new_device_and_success_resets_only_own_channel(client):
    await signup(client)
    await register(client)
    assert await wrong_logins(client, 5) == [401, 401, 401, 401, 403]
    assert error_of(await login_raw(client)) == (403, "ACCOUNT_LOCKED")
    assert await wrong_logins(client, 3, NO_COOKIE) == [401, 401, 401]  # 새 기기 채널은 따로 센다
    challenge = await login_raw(client, headers=NO_COOKIE)
    assert challenge.json()["data"]["status"] == "DEVICE_VERIFICATION_REQUIRED"
    # 새 기기 채널의 성공은 그 채널만 0으로: 등록 기기 채널의 잠금은 그대로
    assert await lock_state(device=False) == (0, False) and await lock_state(device=True) == (5, True)


async def test_new_device_channel_locked_blocks_device_login_step_too(client):
    await signup(client)
    challenge = (await login_raw(client)).json()["data"]["challenge_token"]
    await wrong_logins(client, 5)
    response = await auto_device_login(client, challenge)  # 챌린지를 받은 뒤 잠겼다
    assert error_of(response) == (403, "ACCOUNT_LOCKED")
    assert await device_rows() == []


async def test_password_change_counts_on_the_channel_of_the_device_cookie(client):
    await signup(client)
    session = (await register(client)).json()["data"]
    bad = {"current_password": WRONG, "new_password": NEW_PASSWORD}
    await client.patch("/users/me/password", json=bad, headers=bearer(session))
    assert await lock_state(device=True) == (1, False) and await lock_state(device=False) == (0, False)
    await client.patch("/users/me/password", json=bad, headers={**bearer(session), **NO_COOKIE})  # 쿠키 없이 = 훔친 세션
    assert await lock_state(device=True) == (1, False) and await lock_state(device=False) == (1, False)
    for _ in range(4):
        await client.patch("/users/me/password", json=bad, headers={**bearer(session), **NO_COOKIE})
    assert await lock_state(device=False) == (5, True)
    good = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    assert error_of(await client.patch("/users/me/password", json=good, headers={**bearer(session), **NO_COOKIE})) == (403, "ACCOUNT_LOCKED")
    # 주인의 등록 기기는 바꿀 수 있고, 바꿔도 기기는 유지된다
    ok = await client.patch("/users/me/password", json=good, headers=bearer(session))
    assert ok.status_code == 200
    assert len(await device_rows()) == 1 and (await device_rows())[0].revoked_at is None


# ── 기기 목록·해제 ───────────────────────────────────────────────────


async def test_list_and_revoke_devices(client):
    await signup(client)
    first_device = cookie_value(await register(client), "device_token")
    # 쿠키 없는 다른 브라우저에서 한 번 더 등록 → 단일 세션이라 앞의 세션은 끊기지만 기기는 둘
    challenge = (await login_raw(client, headers=NO_COOKIE)).json()["data"]["challenge_token"]
    second = await auto_device_login(client, challenge)
    second_session, second_device = second.json()["data"], cookie_value(second, "device_token")
    as_second = {**bearer(second_session), **cookie_header(device_token=second_device)}

    listed = await client.get("/users/me/devices", headers=as_second)
    assert listed.status_code == 200
    rows = listed.json()["data"]
    assert len(rows) == 2 and set(rows[0]) == {"device_id", "label", "created_at", "last_used_at", "current"}
    assert [r["current"] for r in rows] == [True, False]  # 최근 사용 순: 방금 등록한 두 번째 기기가 먼저
    no_cookie = {**bearer(second_session), **NO_COOKIE}
    assert [r["current"] for r in (await client.get("/users/me/devices", headers=no_cookie)).json()["data"]] == [False, False]
    second_id, first_id = rows[0]["device_id"], rows[1]["device_id"]

    # Origin이 없거나 다르면 403, 아무것도 해제되지 않는다
    for origin in ("http://evil.example", ""):
        r = await client.delete(f"/users/me/devices/{first_id}", headers={**as_second, "Origin": origin})
        assert error_of(r) == (403, "CSRF_ORIGIN")
    assert len((await client.get("/users/me/devices", headers=as_second)).json()["data"]) == 2

    # 다른 기기를 해제하면 기기 쿠키는 건드리지 않는다
    other = await client.delete(f"/users/me/devices/{first_id}", headers=as_second)
    assert other.status_code == 200 and "device_token" not in set_cookies(other)
    assert error_of(await client.delete(f"/users/me/devices/{first_id}", headers=as_second)) == (404, "DEVICE_NOT_FOUND")
    # 해제된 기기의 쿠키는 새 기기 취급
    assert (await login_raw(client, headers=cookie_header(device_token=first_device))).json()["data"]["status"] == "DEVICE_VERIFICATION_REQUIRED"

    # 현재 기기를 해제하면 기기 쿠키를 지운다. 세션은 이어진다
    gone = await client.delete(f"/users/me/devices/{second_id}", headers=as_second)
    assert gone.status_code == 200
    assert int(set_cookies(gone)["device_token"]["max-age"]) == 0
    assert (await client.get("/users/me", headers=bearer(second_session))).status_code == 200
    assert (await client.get("/users/me/devices", headers=as_second)).json()["data"] == []  # 해제된 기기는 목록에 없다


async def test_cannot_revoke_someone_elses_device_and_requires_login(client):
    await signup(client)
    other = {"login_id": "otheruser", "password": PASSWORD, "name": "스티브", "phone": "010-9999-0000"}
    assert (await client.post("/users/signup", json=other)).status_code == 201
    await register(client)  # ironman의 기기 1번
    stranger = (await register_other(client)).json()["data"]
    assert error_of(await client.delete("/users/me/devices/1", headers=bearer(stranger))) == (404, "DEVICE_NOT_FOUND")
    rows = await device_rows(1)
    assert [(r.device_id, r.revoked_at) for r in rows] == [(1, None)]
    assert (await client.get("/users/me/devices")).status_code == 401
    assert (await client.delete("/users/me/devices/1")).status_code == 401


async def register_other(client):
    challenge = (await login_raw(client, login_id="otheruser")).json()["data"]["challenge_token"]
    return await auto_device_login(client, challenge)


# ── 관리자 해제·재설정 (복구 API의 비밀번호 재설정은 test_recovery, 탈퇴는 test_withdrawal) ──


async def test_admin_unlock_and_reset_clear_both_channels(client):
    from avengers_bank import admin

    await signup(client)
    await register(client)
    for headers in (None, NO_COOKIE):
        await wrong_logins(client, 5, headers)
    assert await lock_state(True) == (5, True) and await lock_state(False) == (5, True)
    assert await admin.unlock(LOGIN_ID) is True
    assert await lock_state(True) == (0, False) and await lock_state(False) == (0, False)

    for headers in (None, NO_COOKIE):
        await wrong_logins(client, 5, headers)
    assert await admin.reset_password(LOGIN_ID, "Adm1n-Reset!") is True
    assert await lock_state(True) == (0, False) and await lock_state(False) == (0, False)
    assert all(d.revoked_at is not None for d in await device_rows())
    await client.post(f"/dev/users/{LOGIN_ID}/unlock")  # 개발용 해제도 같은 함수
