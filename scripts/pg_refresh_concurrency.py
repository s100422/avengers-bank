"""동시 토큰 갱신: 같은 갱신 토큰으로 10번 동시에 갱신해도 정확히 1번만 새 토큰이 나오고,
나머지는 '이미 교체된 토큰 재사용'으로 걸려 그 세션(family) 전체가 끊긴다.
잠금(SELECT ... FOR UPDATE)을 뺀 대조군에서는 여러 번 성공해 세션이 여러 갈래로 갈라진다(재사용 감지 무력화).

실제 API(POST /users/token/refresh)를 ASGI로 직접 부른다.

실행: uv run python scripts/pg_refresh_concurrency.py
"""

import asyncio
from collections import Counter

import httpx

from _common import check, cleanup, connect, finish, one, run, signup_via_api
from avengers_bank.core.database import engine
from avengers_bank.domains.users.repository import user_repository
from avengers_bank.main import app

LOGIN, PASSWORD, TRIES = "verify_refresh", "Passw0rd!23", 10


def label(r):
    return "OK" if r.status_code == 200 else r.json()["error"]["code"]


async def login(client):
    data = (await client.post("/users/login", json={"login_id": LOGIN, "password": PASSWORD})).json()["data"]
    return data["refresh_token"]


async def refresh_all(client, token):
    return await asyncio.gather(*[client.post("/users/token/refresh", json={"refresh_token": token}) for _ in range(TRIES)])


async def amain():
    good = True
    user_id_sql = "(select user_id from users where login_id = :l)"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        body = {"login_id": LOGIN, "password": PASSWORD, "name": "검증", "phone": "010-0000-0000"}
        await signup_via_api(client, body)  # 휴대폰 인증 → 가입 (C-090)

        print(f"1) 같은 갱신 토큰으로 {TRIES}번 동시에 갱신 (잠금 있음)")
        responses = await refresh_all(client, await login(client))
        results = Counter(label(r) for r in responses)
        print("  ", dict(results))
        good &= check("정확히 1번만 새 토큰이 나오고 나머지는 REFRESH_TOKEN_REUSED", results == Counter({"OK": 1, "REFRESH_TOKEN_REUSED": TRIES - 1}))
        winner = next(r for r in responses if r.status_code == 200).json()["data"]["refresh_token"]
        again = await client.post("/users/token/refresh", json={"refresh_token": winner})
        good &= check("재사용이 감지됐으므로 이긴 쪽이 받은 새 토큰도 끊겼다 (세션 전체 폐기)", label(again) == "INVALID_REFRESH_TOKEN")
        alive = one(f"select count(*) from refresh_tokens where user_id = {user_id_sql} and revoked_at is null", l=LOGIN)
        good &= check("살아 있는 갱신 토큰이 0개", alive == 0)

        print("2) 대조군: 잠금 없이 같은 갱신을 동시에 → 여러 번 성공해 세션이 갈라져야 한다")
        real = user_repository.find_refresh_token

        async def no_lock(db, token_hash, *, for_update=False):
            row = await real(db, token_hash)  # 잠그지 않고 읽은 뒤 양보해 경쟁 구간을 넓힌다
            await asyncio.sleep(0.05)
            return row

        # 사용자 행 잠금(lock_user)도 같은 사용자의 갱신을 한 줄로 세우므로 함께 뺀다
        real_lock = user_repository.lock_user
        user_repository.find_refresh_token = no_lock
        user_repository.lock_user = user_repository.find_by_id
        try:
            results = Counter(label(r) for r in await refresh_all(client, await login(client)))
        finally:
            user_repository.find_refresh_token = real
            user_repository.lock_user = real_lock
        print("  ", dict(results))
        good &= check("잠금이 없으면 같은 토큰으로 여러 번 갱신된다 (검증이 문제를 알아본다)", results["OK"] > 1)
    return good


def main():
    connect()
    cleanup(LOGIN)  # 이전 실행이 중간에 끊겨서 남긴 찌꺼기 제거 (사용자는 API로 새로 가입한다)
    try:
        passed = run(amain())
    finally:
        cleanup(LOGIN)
        run(engine.dispose())
    finish(passed, "통과: 동시 갱신에서도 갱신 토큰은 한 번만 쓰인다" if passed else "실패: 위 ✘ 항목을 확인한다")


if __name__ == "__main__":
    main()
