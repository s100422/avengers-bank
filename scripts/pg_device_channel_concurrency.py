"""로그인 채널 분리 (B1): 새 기기 채널과 등록 기기 채널의 실패 카운터·잠금이 서로 독립이고, 각각 원자적이다.

1) 쿠키 없는 새 기기로 30곳(서로 다른 IP)에서 동시에 틀린 비밀번호 → 비밀번호 검증은 정확히 5번, 새 기기 채널만 잠김.
   그 사이/뒤에 주인의 등록 기기(기기 쿠키)로 로그인하면 성공한다. 새 기기로는 맞는 비밀번호도 403.
2) 반대로 등록 기기 채널을 30곳 동시에 틀려 잠가도 검증은 정확히 5번, 새 기기 채널은 영향이 없다(맞는 비밀번호 → 기기 인증 챌린지).
3) 대조군: 선증가를 '읽고 → 나중에 쓰기'로 바꾸면 5번보다 많이 검증된다 (검증이 문제를 알아본다).

잠금은 같은 UPDATE 문장 하나(count_login_attempt, 컬럼만 채널별)가 하므로 채널이 달라도 같은 원자성을 가진다.
기기는 SQL로 직접 등록한다(register_device_sql): 실제 인증 흐름은 번호당 발송 한도가 있어 반복 준비가 안 된다.
실제 API(POST /users/login)를 ASGI로 직접 부른다. 마이그레이션 9e0f1a2b3c4d 적용 후 실행.

실행: uv run python scripts/pg_device_channel_concurrency.py
"""

import asyncio
from collections import Counter

import httpx
from sqlalchemy import select

from _common import check, cleanup, connect, execute, finish, one, register_device_sql, run, signup_via_api
from avengers_bank.core.database import engine
from avengers_bank.core.security import DUMMY_HASH
from avengers_bank.domains.users import service as user_service_module
from avengers_bank.domains.users.models import User
from avengers_bank.domains.users.repository import _channel, user_repository
from avengers_bank.main import app

LOGIN, PASSWORD, PHONE, TRIES = "verify_device_chan", "Passw0rd!23", "010-0000-0000", 30
verified: list[str] = []


def client_from(n: int) -> httpx.AsyncClient:
    # 서로 다른 IP: IP 한도(20회)가 아니라 계정 잠금만 보이게
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(f"10.8.{n // 250}.{n % 250}", 1234)), base_url="http://test")


def label(r):
    return r.json()["data"]["status"] if r.status_code == 200 else r.json()["error"]["code"]


async def login(c, password, device_token=None):
    headers = {"Cookie": f"device_token={device_token}"} if device_token else None
    return await c.post("/users/login", json={"login_id": LOGIN, "password": password}, headers=headers)


async def wrong_everywhere(device_token=None) -> Counter:
    clients = [client_from(n) for n in range(TRIES)]
    try:
        return Counter(label(r) for r in await asyncio.gather(*[login(c, "Wrong0pass!", device_token) for c in clients]))
    finally:
        for c in clients:
            await c.aclose()


async def one_login(password, device_token=None, n=999) -> str:
    async with client_from(n) as c:
        return label(await login(c, password, device_token))


def state(column: str):
    return one(f"select {column} from users where login_id = :l", l=LOGIN)


def reset():
    execute(
        "update users set failed_login_count = 0, login_locked_at = null,"
        " device_failed_login_count = 0, device_login_locked_at = null where login_id = :l", l=LOGIN,
    )
    verified.clear()


def sane(results: Counter) -> bool:
    # 4번 401, 5번째 실패는 403(잠금). 나머지는 잠기기 전에 온 것은 429(검증 중), 잠긴 뒤 온 것은 403
    return (
        results["INVALID_CREDENTIALS"] == 4 and results["ACCOUNT_LOCKED"] >= 1
        and results["ACCOUNT_LOCKED"] + results["TOO_MANY_LOGIN_ATTEMPTS"] == TRIES - 4
    )


async def amain():
    good = True
    real_verify = user_service_module.verify_password

    def counting_verify(password, hashed):
        if hashed != DUMMY_HASH:
            verified.append(password)
        return real_verify(password, hashed)

    user_service_module.verify_password = counting_verify
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await signup_via_api(client, {"login_id": LOGIN, "password": PASSWORD, "name": "검증", "phone": PHONE})
        device = register_device_sql(LOGIN)

        print(f"1) 새 기기 채널을 {TRIES}곳에서 동시에 틀려 잠근다")
        reset()
        results = await wrong_everywhere()
        print("  ", dict(results), f"검증 {len(verified)}번")
        good &= check("비밀번호 검증은 정확히 5번", len(verified) == 5)
        good &= check("401 4개, 나머지는 403(잠금) 또는 429(검증 중)", sane(results))
        good &= check("새 기기 채널만 잠김 (5, 잠김 / 등록 기기 0, 안 잠김)", (
            state("failed_login_count"), state("login_locked_at is not null"),
            state("device_failed_login_count"), state("device_login_locked_at is not null"),
        ) == (5, True, 0, False))
        good &= check("잠긴 새 기기는 맞는 비밀번호도 403", await one_login(PASSWORD) == "ACCOUNT_LOCKED")
        good &= check("그래도 주인의 등록 기기는 로그인된다 (OK)", await one_login(PASSWORD, device) == "OK")

        print(f"2) 등록 기기 채널을 {TRIES}곳에서 동시에 틀려 잠근다")
        reset()
        results = await wrong_everywhere(device)
        print("  ", dict(results), f"검증 {len(verified)}번")
        good &= check("비밀번호 검증은 정확히 5번", len(verified) == 5)
        good &= check("401 4개, 나머지는 403(잠금) 또는 429(검증 중)", sane(results))
        good &= check("등록 기기 채널만 잠김 (새 기기 0, 안 잠김 / 등록 기기 5, 잠김)", (
            state("failed_login_count"), state("login_locked_at is not null"),
            state("device_failed_login_count"), state("device_login_locked_at is not null"),
        ) == (0, False, 5, True))
        good &= check("잠긴 등록 기기는 맞는 비밀번호도 403", await one_login(PASSWORD, device) == "ACCOUNT_LOCKED")
        good &= check("새 기기는 영향 없음: 맞는 비밀번호 → 기기 인증 챌린지", await one_login(PASSWORD) == "DEVICE_VERIFICATION_REQUIRED")

        print("3) 대조군: 선증가를 '읽고 → 나중에 쓰기'로 바꾸면 5번보다 많이 검증되어야 한다 (등록 기기 채널)")
        reset()
        real_count = user_repository.count_login_attempt

        async def read_then_write(db, user_id, max_failures, device=False):
            count, _ = _channel(device)
            current = await db.scalar(select(count).where(User.user_id == user_id))
            await asyncio.sleep(0.05)  # 읽은 뒤 양보해 경쟁 구간을 넓힌다
            if current >= max_failures:
                return None
            user = await db.get(User, user_id)
            setattr(user, count.key, current + 1)
            return current + 1

        user_repository.count_login_attempt = read_then_write
        try:
            results = await wrong_everywhere(device)
        finally:
            user_repository.count_login_attempt = real_count
        print("  ", dict(results), f"검증 {len(verified)}번")
        good &= check("대조군은 5번보다 많이 검증된다 (검증이 문제를 알아본다)", len(verified) > 5)
    finally:
        user_service_module.verify_password = real_verify
    return good


def main():
    connect()
    cleanup(LOGIN)  # 이전 실행이 중간에 끊겨서 남긴 찌꺼기 제거 (사용자는 API로 새로 가입한다)
    try:
        passed = run(amain())
    finally:
        cleanup(LOGIN)
        run(engine.dispose())
    finish(passed, "통과: 두 채널의 잠금은 서로 독립이고 각각 원자적이다" if passed else "실패: 위 ✘ 항목을 확인한다")


if __name__ == "__main__":
    main()
