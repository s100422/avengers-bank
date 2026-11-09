"""동시 로그인 실패와 잠금 (C-090): 같은 아이디로 30곳(서로 다른 IP)에서 동시에 틀린 비밀번호를 보내도
비밀번호는 정확히 5번만 검증되고 아이디가 잠긴다. 실패 횟수를 검증 *전에* 한 UPDATE 문장으로 먼저 올리기 때문이다.
대조군: 그 선증가를 '읽고(SELECT) → 나중에 쓰기(UPDATE)'로 바꾸면 모두 같은 옛 값을 읽어 5번보다 많이 검증된다.
3) 같은 번호로 인증번호를 동시에 8번 요청해도 3번만 발송된다(번호별 advisory lock).

실제 API(POST /users/login, POST /verification/phone/send)를 ASGI로 직접 부른다. 마이그레이션 6b7c8d9e0f1a 적용 후 실행.

실행: uv run python scripts/pg_login_lock_concurrency.py
"""

import asyncio
from collections import Counter

import httpx
from sqlalchemy import select

from _common import check, cleanup, connect, execute, finish, one, run, signup_via_api
from avengers_bank.core.database import engine
from avengers_bank.core.login_limiter import verification_ip_limiter
from avengers_bank.core.security import DUMMY_HASH
from avengers_bank.domains.users import service as user_service_module
from avengers_bank.domains.users.models import User
from avengers_bank.domains.users.repository import user_repository
from avengers_bank.main import app

LOGIN, PASSWORD, PHONE, TRIES = "verify_login_lock", "Passw0rd!23", "010-0000-0000", 30
verified: list[str] = []


def device(n: int) -> httpx.AsyncClient:
    # 서로 다른 IP: IP 한도(20회)가 아니라 아이디 잠금만 보이게
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(f"10.9.{n // 250}.{n % 250}", 1234)), base_url="http://test")


def label(r):
    return "OK" if r.status_code == 200 else r.json()["error"]["code"]


async def wrong_logins_everywhere() -> Counter:
    devices = [device(n) for n in range(TRIES)]
    try:
        responses = await asyncio.gather(
            *[d.post("/users/login", json={"login_id": LOGIN, "password": "Wrong0pass!"}) for d in devices]
        )
    finally:
        for d in devices:
            await d.aclose()
    return Counter(label(r) for r in responses)


def reset_lock():
    execute(
        "update users set failed_login_count = 0, login_locked_at = null,"
        " device_failed_login_count = 0, device_login_locked_at = null where login_id = :l", l=LOGIN,
    )
    verified.clear()


async def amain():
    good = True
    real_verify = user_service_module.verify_password

    def counting_verify(password, hashed):
        if hashed != DUMMY_HASH:  # 없는 아이디용 가짜 해시 검증은 세지 않는다
            verified.append(password)
        return real_verify(password, hashed)

    user_service_module.verify_password = counting_verify
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await signup_via_api(client, {"login_id": LOGIN, "password": PASSWORD, "name": "검증", "phone": PHONE})

        print(f"1) 같은 아이디로 {TRIES}곳에서 동시에 틀린 비밀번호 (원자적 선증가)")
        reset_lock()
        results = await wrong_logins_everywhere()
        print("  ", dict(results), f"검증 {len(verified)}번")
        good &= check("비밀번호 검증은 정확히 5번", len(verified) == 5)
        good &= check("401 4개, 나머지는 잠금 403 또는 검증 중 429(잠기기 전에 온 동시 요청)",
                      results["INVALID_CREDENTIALS"] == 4 and results["ACCOUNT_LOCKED"] >= 1
                      and results["ACCOUNT_LOCKED"] + results["TOO_MANY_LOGIN_ATTEMPTS"] == TRIES - 4)
        # 쿠키 없는 새 기기 채널이므로 failed_login_count/login_locked_at이 센다(등록 기기 채널은 pg_device_channel_concurrency.py)
        count, locked = one("select failed_login_count from users where login_id = :l", l=LOGIN), one(
            "select login_locked_at is not null from users where login_id = :l", l=LOGIN
        )
        good &= check("failed_login_count = 5, 잠김", (count, locked) == (5, True))
        async with device(999) as d:
            ok = await d.post("/users/login", json={"login_id": LOGIN, "password": PASSWORD})
        good &= check("잠긴 뒤에는 맞는 비밀번호도 403", label(ok) == "ACCOUNT_LOCKED")

        print("2) 대조군: 선증가를 '읽고 → 나중에 쓰기'로 바꾸면 5번보다 많이 검증되어야 한다")
        reset_lock()
        real_count = user_repository.count_login_attempt

        async def read_then_write(db, user_id, max_failures, device=False):  # 쿠키 없는 요청 = 새 기기 채널
            current = await db.scalar(select(User.failed_login_count).where(User.user_id == user_id))
            await asyncio.sleep(0.05)  # 읽은 뒤 양보해 경쟁 구간을 넓힌다
            if current >= max_failures:
                return None
            user = await db.get(User, user_id)
            user.failed_login_count = current + 1
            return current + 1

        user_repository.count_login_attempt = read_then_write
        try:
            results = await wrong_logins_everywhere()
        finally:
            user_repository.count_login_attempt = real_count
        print("  ", dict(results), f"검증 {len(verified)}번")
        good &= check("대조군은 5번보다 많이 검증된다 (검증이 문제를 알아본다)", len(verified) > 5)

        print("3) 같은 번호로 인증번호를 동시에 8번 요청 → 3번만 발송 (번호별 advisory lock)")
        execute("delete from verification_codes where phone = :p", p=PHONE)
        verification_ip_limiter.clear()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            responses = await asyncio.gather(*[
                client.post("/verification/phone/send", json={"phone": PHONE, "purpose": "SIGNUP_PHONE"}) for _ in range(8)
            ])
        results = Counter(label(r) for r in responses)
        print("  ", dict(results))
        rows = one("select count(*) from verification_codes where phone = :p", p=PHONE)
        good &= check("3번 성공, 5번 TOO_MANY_VERIFICATION_REQUESTS, 행 3개",
                      results == Counter({"OK": 3, "TOO_MANY_VERIFICATION_REQUESTS": 5}) and rows == 3)
    finally:
        user_service_module.verify_password = real_verify
    return good


def main():
    connect()
    cleanup(LOGIN)  # 이전 실행이 중간에 끊겨서 남긴 찌꺼기 제거 (사용자는 API로 새로 가입한다)
    execute("delete from verification_codes where phone = :p", p=PHONE)
    try:
        passed = run(amain())
    finally:
        cleanup(LOGIN)
        execute("delete from verification_codes where phone = :p", p=PHONE)
        run(engine.dispose())
    finish(passed, "통과: 동시 요청에도 로그인 검증은 5번, 그 뒤 잠금" if passed else "실패: 위 ✘ 항목을 확인한다")


if __name__ == "__main__":
    main()
