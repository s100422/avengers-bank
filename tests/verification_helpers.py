"""테스트용 휴대폰 인증 도우미: 발송 → 개발용 문자함(GET /dev/sms)에서 코드 읽기 → 확인 → 증표."""

import re
from datetime import datetime, timezone

from sqlalchemy import update

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.login_limiter import verification_ip_limiter
from avengers_bank.domains.verification.models import VerificationCode


async def read_code(client, phone: str) -> str:
    """그 번호로 온 가장 최근 문자의 인증번호."""
    messages = (await client.get("/dev/sms", params={"phone": phone})).json()["data"]
    return re.search(r"\d{6}", messages[0]["text"]).group()


async def exempt_from_send_limits(verification_id: int) -> None:
    """자동 인증이 발송 제한(번호당 15분 3번, IP당 10번)을 쓰지 않게 한다: 같은 번호로 여러 명이 가입하는 기존 테스트용.

    발송 제한은 created_at을 세므로 그 행을 오래전에 만든 것으로 바꾸고(유효 시간 expires_at은 그대로), IP 기록을 지운다.
    """
    async with SessionLocal() as db, db.begin():
        await db.execute(
            update(VerificationCode)
            .where(VerificationCode.verification_id == verification_id)
            .values(created_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
        )
    verification_ip_limiter.clear()


async def phone_token(client, phone: str, purpose: str = "SIGNUP_PHONE", headers=None, *, exempt: bool = False) -> str:
    """인증을 끝까지 해서 verification_token을 돌려준다. headers가 있으면 로그인한 사용자용 발송(send-for-me)."""
    url = "/verification/phone/send-for-me" if headers else "/verification/phone/send"
    sent = await client.post(url, json={"phone": phone, "purpose": purpose}, headers=headers)
    assert sent.status_code == 200, sent.text
    verification_id = sent.json()["data"]["verification_id"]
    if exempt:
        await exempt_from_send_limits(verification_id)
    code = await read_code(client, phone)
    verified = await client.post("/verification/phone/verify", json={"verification_id": verification_id, "code": code})
    assert verified.status_code == 200, verified.text
    return verified.json()["data"]["verification_token"]


async def auto_signup_token(client, phone) -> dict:
    """BankClient가 가입 요청에 붙일 {'phone_verification_token': ...}. 번호가 없거나 틀려 발송이 안 되면 {}
    (그러면 가입 요청이 원래 받아야 할 422를 그대로 받는다)."""
    if not isinstance(phone, str):
        return {}
    sent = await client.post("/verification/phone/send", json={"phone": phone, "purpose": "SIGNUP_PHONE"})
    if sent.status_code != 200:
        return {}
    verification_id = sent.json()["data"]["verification_id"]
    await exempt_from_send_limits(verification_id)
    code = await read_code(client, phone)
    verified = await client.post("/verification/phone/verify", json={"verification_id": verification_id, "code": code})
    return {"phone_verification_token": verified.json()["data"]["verification_token"]}
