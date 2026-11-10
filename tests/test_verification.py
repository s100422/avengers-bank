"""휴대폰 인증번호 (C-090): 발송·개발용 문자함·확인·만료·5회·1회성·발송 제한·purpose 불일치·HMAC 저장, 가입·번호 변경."""

import asyncio
import hashlib
import hmac
import re
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select, update

from avengers_bank.core.config import Settings, get_settings
from avengers_bank.core.database import SessionLocal, engine
from avengers_bank.core.login_limiter import verification_ip_limiter
from avengers_bank.domains.users.models import User
from avengers_bank.domains.verification.models import VerificationCode
from avengers_bank.domains.verification.service import consume_verification, send_notice
from avengers_bank.domains.verification.sms import dev_messages
from tests.verification_helpers import phone_token, read_code

pytestmark = pytest.mark.anyio

PHONE = "010-1234-5678"
SIGNUP = {"login_id": "ironman", "password": "Passw0rd!23", "name": "토니", "phone": PHONE}


@pytest.fixture(autouse=True)
async def manual(client):
    client.auto_phone_verification = False  # 인증 자체를 보므로 자동 인증을 끄고 직접 보낸다
    yield
    await engine.dispose()  # 동시 요청 테스트가 묶은 커넥션 풀 대기열을 다음 테스트(다른 이벤트 루프)로 넘기지 않는다


async def send(client, phone=PHONE, purpose="SIGNUP_PHONE"):
    return await client.post("/verification/phone/send", json={"phone": phone, "purpose": purpose})


async def verify(client, verification_id, code):
    return await client.post("/verification/phone/verify", json={"verification_id": verification_id, "code": code})


def error(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


async def row(verification_id) -> VerificationCode:
    async with SessionLocal() as db:
        return await db.get(VerificationCode, verification_id)


async def sent_id(client, phone=PHONE) -> int:
    response = await send(client, phone)
    assert response.status_code == 200, response.text
    return response.json()["data"]["verification_id"]


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


# ── 발송·문자함 ──────────────────────────────────────────────────────


async def test_send_returns_id_and_writes_to_dev_inbox(client):
    response = await send(client, "01012345678")  # 휴대폰 번호 정규화를 같이 쓴다
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["expires_in"] == 600 and isinstance(data["verification_id"], int)
    messages = (await client.get("/dev/sms", params={"phone": PHONE})).json()["data"]
    assert len(messages) == 1
    assert re.fullmatch(r"\[AvengersBank\] 인증번호 \d{6} \(10분 안에 입력\)\. 타인에게 알려 주지 마세요\.", messages[0]["text"])


async def test_dev_inbox_is_per_phone_newest_first_max_20(client):
    for _ in range(25):
        await send_notice(PHONE, "알림")
    await send_notice("010-9999-8888", "다른 사람")
    await sent_id(client)
    messages = (await client.get("/dev/sms", params={"phone": PHONE})).json()["data"]
    assert len(messages) == 20
    assert "인증번호" in messages[0]["text"] and messages[1]["text"] == "[AvengersBank] 알림"
    assert all("다른 사람" not in m["text"] for m in messages)
    assert (await client.get("/dev/sms", params={"phone": "02-123-4567"})).status_code == 422


async def test_send_does_not_reveal_registered_phone(client):
    first = await send(client)
    client.auto_phone_verification = True
    await client.post("/users/signup", json=SIGNUP)  # 이제 이 번호로 가입된 사용자가 있다
    second = await send(client)
    assert first.json()["message"] == second.json()["message"] and set(first.json()["data"]) == set(second.json()["data"])


@pytest.mark.parametrize("purpose", ["CHANGE_PHONE", "PASSWORD_RESET", "ACCOUNT_PASSWORD_RESET", "NOPE"])
async def test_public_send_allows_only_signup_purpose(client, purpose):
    assert error(await send(client, purpose=purpose)) == (422, "VALIDATION_ERROR")


async def test_send_for_me_requires_login_and_change_phone_purpose(client, make_user):
    body = {"phone": "010-9999-8888", "purpose": "CHANGE_PHONE_NEW"}
    assert (await client.post("/verification/phone/send-for-me", json=body)).status_code == 401
    client.auto_phone_verification = True
    headers = await make_user()
    signup_purpose = {**body, "purpose": "SIGNUP_PHONE"}
    assert (await client.post("/verification/phone/send-for-me", json=signup_purpose, headers=headers)).status_code == 422
    sent = await client.post("/verification/phone/send-for-me", json=body, headers=headers)
    assert sent.status_code == 200
    saved = await row(sent.json()["data"]["verification_id"])
    assert (saved.purpose, saved.phone, saved.user_id) == ("CHANGE_PHONE_NEW", "010-9999-8888", 1)
    old = await client.post("/verification/phone/send-for-me", json={"phone": "010-7777-6666", "purpose": "CHANGE_PHONE_OLD"}, headers=headers)
    assert old.status_code == 200
    old_row = await row(old.json()["data"]["verification_id"])
    assert (old_row.purpose, old_row.phone, old_row.user_id) == ("CHANGE_PHONE_OLD", PHONE, 1)


# ── 저장 방식 ────────────────────────────────────────────────────────


async def test_code_is_stored_only_as_hmac_with_server_secret(client):
    verification_id = await sent_id(client)
    code = await read_code(client, PHONE)
    saved = await row(verification_id)
    key = get_settings().jwt_secret_key.get_secret_value().encode()
    assert saved.code_hash == hmac.new(key, f"verification:{verification_id}:{code}".encode(), hashlib.sha256).hexdigest()
    assert saved.code_hash != hashlib.sha256(code.encode()).hexdigest()  # 비밀키 없이 100만 개를 해 봐도 안 나온다
    assert code not in saved.code_hash
    assert saved.expires_at.replace(tzinfo=timezone.utc) - saved.created_at.replace(tzinfo=timezone.utc) == timedelta(minutes=10)


# ── 확인 ────────────────────────────────────────────────────────────


async def test_verify_returns_short_lived_verification_token_not_usable_as_access_token(client):
    verification_id = await sent_id(client)
    response = await verify(client, verification_id, await read_code(client, PHONE))
    assert response.status_code == 200
    token = response.json()["data"]["verification_token"]
    payload = jwt.decode(token, get_settings().jwt_secret_key.get_secret_value(), algorithms=["HS256"])
    assert (payload["typ"], payload["purpose"], payload["phone"], payload["vid"]) == (
        "verification", "SIGNUP_PHONE", PHONE, verification_id
    )
    assert payload["exp"] - payload["iat"] == 600
    assert (await row(verification_id)).verified_at is not None
    assert (await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401


async def test_wrong_code_counts_and_five_attempts_invalidate(client):
    verification_id = await sent_id(client)
    code = await read_code(client, PHONE)
    for n in range(1, 6):
        response = await verify(client, verification_id, wrong(code))
        assert error(response) == (400, "INVALID_VERIFICATION_CODE")
        assert response.json()["error"]["message"] == f"인증번호가 올바르지 않습니다. ({n}/5)"
    late = await verify(client, verification_id, code)  # 맞는 코드도 5회를 다 쓰면 끝
    assert error(late) == (400, "VERIFICATION_EXPIRED")
    assert late.json()["error"]["message"] == "인증번호가 만료되었습니다. 다시 받아 주세요."
    assert (await row(verification_id)).attempts == 5


async def test_malformed_code_counts_as_wrong_attempt(client):
    verification_id = await sent_id(client)
    assert error(await verify(client, verification_id, "abc")) == (400, "INVALID_VERIFICATION_CODE")
    assert (await row(verification_id)).attempts == 1


async def test_concurrent_wrong_codes_are_compared_only_five_times(client):
    verification_id = await sent_id(client)
    code = await read_code(client, PHONE)
    responses = await asyncio.gather(*(verify(client, verification_id, wrong(code)) for _ in range(20)))
    codes = sorted(r.json()["error"]["code"] for r in responses)
    assert codes == ["INVALID_VERIFICATION_CODE"] * 5 + ["VERIFICATION_EXPIRED"] * 15
    assert (await row(verification_id)).attempts == 5


async def test_expired_code_is_rejected(client):
    verification_id = await sent_id(client)
    async with SessionLocal() as db, db.begin():
        await db.execute(
            update(VerificationCode).where(VerificationCode.verification_id == verification_id)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
    assert error(await verify(client, verification_id, await read_code(client, PHONE))) == (400, "VERIFICATION_EXPIRED")


async def test_code_can_be_verified_only_once_and_unknown_id_is_expired(client):
    verification_id = await sent_id(client)
    code = await read_code(client, PHONE)
    assert (await verify(client, verification_id, code)).status_code == 200
    assert error(await verify(client, verification_id, code)) == (400, "VERIFICATION_EXPIRED")
    assert error(await verify(client, 9999, "123456")) == (400, "VERIFICATION_EXPIRED")


# ── 발송 제한 ────────────────────────────────────────────────────────


async def test_same_phone_three_sends_per_15_minutes_counted_in_db(client):
    for _ in range(3):
        assert (await send(client)).status_code == 200
    blocked = await send(client)
    assert error(blocked) == (429, "TOO_MANY_VERIFICATION_REQUESTS")
    assert 1 <= int(blocked.headers["Retry-After"]) <= 900
    verification_ip_limiter.clear()  # 메모리 한도를 지워도(서버 재시작) DB에서 세므로 그대로 막힌다
    assert error(await send(client)) == (429, "TOO_MANY_VERIFICATION_REQUESTS")
    assert (await send(client, "010-1111-2222")).status_code == 200  # 다른 번호는 별개
    async with SessionLocal() as db, db.begin():  # 15분이 지나면 다시 보낼 수 있다
        await db.execute(
            update(VerificationCode).where(VerificationCode.phone == PHONE)
            .values(created_at=datetime.now(timezone.utc) - timedelta(minutes=16))
        )
    assert (await send(client)).status_code == 200


async def test_same_ip_ten_sends_per_15_minutes(client):
    for n in range(10):
        assert (await send(client, f"010-1000-{n:04d}")).status_code == 200
    assert error(await send(client, "010-1000-9999")) == (429, "TOO_MANY_VERIFICATION_REQUESTS")


# 같은 번호로 동시에 보내도 3번에서 멈추는지(advisory lock)는 SQLite로 볼 수 없다 → scripts/pg_login_lock_concurrency.py 3)


# ── 가입 ────────────────────────────────────────────────────────────


async def test_signup_requires_phone_verification_token(client):
    response = await client.post("/users/signup", json=SIGNUP)
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["msg"] == "필수 항목입니다: 휴대폰 인증"


async def test_signup_with_token_records_phone_verified_at_and_token_is_single_use(client):
    token = await phone_token(client, "01012345678")
    response = await client.post("/users/signup", json={**SIGNUP, "phone_verification_token": token})
    assert response.status_code == 201
    async with SessionLocal() as db:
        user = await db.scalar(select(User))
        assert user.phone_verified_at is not None and user.failed_login_count == 0 and user.login_locked_at is None
        assert (await db.scalar(select(VerificationCode))).consumed_at is not None
    again = await client.post("/users/signup", json={**SIGNUP, "login_id": "hulk", "phone_verification_token": token})
    assert error(again) == (400, "INVALID_VERIFICATION_TOKEN")


async def test_failed_signup_does_not_use_up_the_token(client):
    client.auto_phone_verification = True
    await client.post("/users/signup", json=SIGNUP)
    client.auto_phone_verification = False
    token = await phone_token(client, PHONE, exempt=True)
    duplicate = await client.post("/users/signup", json={**SIGNUP, "phone_verification_token": token})
    assert error(duplicate) == (409, "LOGIN_ID_ALREADY_EXISTS")  # 롤백 → 증표 사용도 되돌려진다
    ok = await client.post("/users/signup", json={**SIGNUP, "login_id": "hulk", "phone_verification_token": token})
    assert ok.status_code == 201


async def test_signup_token_must_match_phone_and_purpose(client, make_user):
    token = await phone_token(client, "010-9999-8888")
    other_phone = await client.post("/users/signup", json={**SIGNUP, "phone_verification_token": token})
    assert error(other_phone) == (400, "INVALID_VERIFICATION_TOKEN")
    garbage = await client.post("/users/signup", json={**SIGNUP, "phone_verification_token": "not-a-token"})
    assert error(garbage) == (400, "INVALID_VERIFICATION_TOKEN")
    unverified = jwt.encode(  # 확인(verify)을 거치지 않은 발송 건으로 증표를 위조해도 verified_at이 없어 거절
        {"typ": "verification", "vid": await sent_id(client), "purpose": "SIGNUP_PHONE", "phone": PHONE,
         "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        get_settings().jwt_secret_key.get_secret_value(), algorithm="HS256",
    )
    assert error(await client.post("/users/signup", json={**SIGNUP, "phone_verification_token": unverified})) == (
        400, "INVALID_VERIFICATION_TOKEN"
    )
    client.auto_phone_verification = True
    headers = await make_user("hulk")
    change = await phone_token(client, "010-5555-4444", "CHANGE_PHONE_NEW", headers, exempt=True)
    wrong_purpose = await client.post("/users/signup", json={**SIGNUP, "phone_verification_token": change})
    assert error(wrong_purpose) == (400, "INVALID_VERIFICATION_TOKEN")


async def test_expired_token_is_rejected(client):
    token = await phone_token(client, PHONE)
    payload = jwt.decode(token, get_settings().jwt_secret_key.get_secret_value(), algorithms=["HS256"])
    old = jwt.encode(
        {**payload, "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        get_settings().jwt_secret_key.get_secret_value(), algorithm="HS256",
    )
    assert error(await client.post("/users/signup", json={**SIGNUP, "phone_verification_token": old})) == (
        400, "INVALID_VERIFICATION_TOKEN"
    )


# ── 번호 변경 ────────────────────────────────────────────────────────


async def test_change_phone_requires_token_for_new_number(client, make_user):
    client.auto_phone_verification = True
    headers = await make_user()
    missing = await client.patch("/users/me", json={"phone": "010-9999-8888"}, headers=headers)
    assert error(missing) == (422, "VALIDATION_ERROR")
    assert (await client.patch("/users/me", json={"name": "페퍼"}, headers=headers)).status_code == 200  # 다른 필드는 불필요
    async with SessionLocal() as db:
        before = (await db.scalar(select(User))).phone_verified_at
    old_token = await phone_token(client, PHONE, "CHANGE_PHONE_OLD", headers)
    new_token = await phone_token(client, "010-9999-8888", "CHANGE_PHONE_NEW", headers)
    ok = await client.post("/users/me/phone-change", json={"current_password": "Passw0rd!23", "phone": "010-9999-8888", "old_phone_verification_token": old_token, "new_phone_verification_token": new_token}, headers=headers)
    assert ok.status_code == 200 and ok.json()["data"]["phone"] == "010-9999-8888"
    async with SessionLocal() as db:
        assert (await db.scalar(select(User))).phone_verified_at > before
    assert "refresh_token" in ok.headers.get("set-cookie", "") and "Max-Age=0" in ok.headers.get("set-cookie", "")
    assert (await client.get("/users/me", headers=headers)).status_code == 401


async def test_phone_change_requires_current_password_even_with_stolen_session_and_new_phone_token(client, make_user):
    client.auto_phone_verification = True
    headers = await make_user()
    old_token = await phone_token(client, PHONE, "CHANGE_PHONE_OLD", headers, exempt=True)
    new_token = await phone_token(client, "010-9999-8888", "CHANGE_PHONE_NEW", headers, exempt=True)
    response = await client.post("/users/me/phone-change", json={
        "current_password": "WrongPass!23", "phone": "010-9999-8888",
        "old_phone_verification_token": old_token, "new_phone_verification_token": new_token,
    }, headers=headers)
    assert error(response) == (400, "INVALID_CURRENT_PASSWORD")
    async with SessionLocal() as db:
        assert (await db.scalar(select(User))).phone == PHONE


async def test_phone_change_rejects_wrong_number_and_wrong_purpose(client, make_user):
    client.auto_phone_verification = True
    headers = await make_user()
    old_token = await phone_token(client, PHONE, "CHANGE_PHONE_OLD", headers, exempt=True)
    signup_token = await phone_token(client, "010-9999-8888", exempt=True)
    wrong_purpose = await client.post("/users/me/phone-change", json={
        "current_password": "Passw0rd!23", "phone": "010-9999-8888",
        "old_phone_verification_token": old_token, "new_phone_verification_token": signup_token,
    }, headers=headers)
    assert error(wrong_purpose) == (400, "INVALID_VERIFICATION_TOKEN")
    new_token = await phone_token(client, "010-9999-8888", "CHANGE_PHONE_NEW", headers, exempt=True)
    wrong_number = await client.post("/users/me/phone-change", json={
        "current_password": "Passw0rd!23", "phone": "010-7777-6666",
        "old_phone_verification_token": old_token, "new_phone_verification_token": new_token,
    }, headers=headers)
    assert error(wrong_number) == (400, "INVALID_VERIFICATION_TOKEN")
    async with SessionLocal() as db:
        assert (await db.scalar(select(User))).phone == PHONE


async def test_change_phone_token_of_another_user_is_rejected(client, make_user):
    client.auto_phone_verification = True
    tony, bruce = await make_user("ironman"), await make_user("hulk")
    old_token = await phone_token(client, PHONE, "CHANGE_PHONE_OLD", tony)
    new_token = await phone_token(client, "010-9999-8888", "CHANGE_PHONE_NEW", bruce)
    stolen = await client.post("/users/me/phone-change", json={"current_password": "Passw0rd!23", "phone": "010-9999-8888", "old_phone_verification_token": old_token, "new_phone_verification_token": new_token}, headers=tony)
    assert error(stolen) == (400, "INVALID_VERIFICATION_TOKEN")
    signup_token = await phone_token(client, "010-5555-4444", exempt=True)
    wrong_purpose = await client.post("/users/me/phone-change", json={"current_password": "Passw0rd!23", "phone": "010-5555-4444", "old_phone_verification_token": old_token, "new_phone_verification_token": signup_token}, headers=tony)
    assert error(wrong_purpose) == (400, "INVALID_VERIFICATION_TOKEN")


# ── 내부 함수·설정 ───────────────────────────────────────────────────


async def test_consume_verification_checks_user_and_is_single_use(client, make_user):
    client.auto_phone_verification = True
    headers = await make_user()
    token = await phone_token(client, "010-9999-8888", "CHANGE_PHONE_NEW", headers)
    async with SessionLocal() as db:
        with pytest.raises(Exception) as caught:
            async with db.begin():
                await consume_verification(db, token, "CHANGE_PHONE_NEW", user_id=2)
        assert caught.value.code == "INVALID_VERIFICATION_TOKEN"
        async with db.begin():
            used = await consume_verification(db, token, "CHANGE_PHONE_NEW", phone="010-9999-8888", user_id=1)
        assert used.consumed_at is not None
        with pytest.raises(Exception):
            async with db.begin():
                await consume_verification(db, token, "CHANGE_PHONE_NEW")


async def test_send_notice_and_sms_sender_setting():
    await send_notice("010-3333-4444", "비밀번호가 재설정되었습니다.")
    assert dev_messages("010-3333-4444")[0][0] == "[AvengersBank] 비밀번호가 재설정되었습니다."
    base = {"database_url": "x", "jwt_secret_key": "k" * 32}
    assert Settings(**base).sms_sender == "dev"
    with pytest.raises(ValueError):
        Settings(**base, sms_sender="real-provider")  # 실제 발송기가 없으니 서버가 시작되지 않는다
