"""단일 세션의 동시성: 같은 사용자의 세션 집합을 바꾸는 작업이 users 행 잠금으로 한 줄로 서는지 확인한다.

1) 같은 사용자로 5곳에서 동시에 로그인 → 살아 있는 세션(family)이 정확히 1개
2) 기기 1의 갱신(회전: 새 행 INSERT)과 다른 곳 로그인을 동시에, 여러 라운드 → 매번 다른 곳 로그인 쪽 1개만 생존
3) 대조군: users 잠금(lock_user)을 뺀 상태로 1) → 살아 있는 세션이 2개 이상 생겨야 한다 (검증이 문제를 알아본다)

잠금이 없으면 왜 깨지나: PostgreSQL READ COMMITTED에서 "다른 세션 폐기" UPDATE는 그 문장 시작 시점에 커밋된 행만 본다.
동시에 진행 중인 로그인·갱신이 INSERT한 새 행은 아직 커밋 전이라 안 보여서 폐기를 피해 간다.

'다른 곳'은 IP가 다른 클라이언트로 흉내 낸다. 로그인 실패 한도(아이디+IP 5회)는 검증 전에 시도를 세므로,
같은 IP에서 동시에 10번 로그인하면 6번째부터 429가 된다 — 기기마다 IP를 달리 하면 실제 상황과도 같다.

실행: uv run python scripts/pg_single_session_concurrency.py  (마이그레이션 4f2a9c7e1b30 적용 후)
"""

import asyncio
from collections import Counter

import httpx

from _common import check, cleanup, connect, finish, one, run, signup_via_api
from avengers_bank.core.database import engine
from avengers_bank.core.security import hash_refresh_token
from avengers_bank.domains.users.repository import user_repository
from avengers_bank.main import app

# TRIES는 5 이하: 로그인 잠금(C-090)은 비밀번호 검증 *전에* 실패 1회를 먼저 세므로, 맞는 비밀번호라도 동시에 6개 이상
# 보내면 6번째부터는 '이미 5번을 다 가져갔다'로 403이 된다(검증이 끝나야 0으로 돌아간다). 그건 이 스크립트가 보려는 게 아니다
LOGIN, PASSWORD, TRIES, ROUNDS = "verify_single", "Passw0rd!23", 5, 15
USER_ID_SQL = "(select user_id from users where login_id = :l)"


def device(n: int) -> httpx.AsyncClient:
    """IP가 다른 기기 하나."""
    transport = httpx.ASGITransport(app=app, client=(f"10.0.0.{n}", 50000))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def label(r):
    return "OK" if r.status_code == 200 else r.json()["error"]["code"]


async def login(client):
    return await client.post("/users/login", json={"login_id": LOGIN, "password": PASSWORD})


def alive_families() -> int:
    return one(
        f"select count(distinct family_id) from refresh_tokens where user_id = {USER_ID_SQL} and revoked_at is null", l=LOGIN
    )


def family_of(refresh_token: str) -> str:
    return one("select family_id from refresh_tokens where token_hash = :h", h=hash_refresh_token(refresh_token))


def alive_family() -> str | None:
    return one(f"select max(family_id) from refresh_tokens where user_id = {USER_ID_SQL} and revoked_at is null", l=LOGIN)


async def login_all(devices):
    return await asyncio.gather(*[login(d) for d in devices])


async def amain():
    good = True
    devices = [device(i + 1) for i in range(TRIES)]
    try:
        body = {"login_id": LOGIN, "password": PASSWORD, "name": "검증", "phone": "010-0000-0000"}
        await signup_via_api(devices[0], body)  # 휴대폰 인증 → 가입 (C-090)

        print(f"1) 같은 사용자로 {TRIES}곳에서 동시에 로그인 (잠금 있음)")
        responses = await login_all(devices)
        print("  ", dict(Counter(label(r) for r in responses)))
        good &= check("모두 로그인 성공 (나중 로그인이 앞 로그인을 끊는다)", all(r.status_code == 200 for r in responses))
        good &= check("살아 있는 세션(family)이 정확히 1개", alive_families() == 1)
        tokens = [r.json()["data"]["refresh_token"] for r in responses]
        refreshed = Counter(label(r) for r in await asyncio.gather(
            *[d.post("/users/token/refresh", json={"refresh_token": t}) for d, t in zip(devices, tokens)]
        ))
        print("   각 기기에서 갱신:", dict(refreshed))
        good &= check(
            f"갱신은 1곳만 성공, {TRIES - 1}곳은 SESSION_REPLACED",
            refreshed == Counter({"OK": 1, "SESSION_REPLACED": TRIES - 1}),
        )

        print(f"2) 기기 1 갱신 ↔ 다른 곳 로그인 동시 실행 × {ROUNDS}라운드")
        first, elsewhere = devices[0], devices[1]
        outcomes, bad_rounds = Counter(), []
        for i in range(ROUNDS):
            token = (await login(first)).json()["data"]["refresh_token"]
            refreshed, other = await asyncio.gather(
                first.post("/users/token/refresh", json={"refresh_token": token}), login(elsewhere)
            )
            outcomes[label(refreshed)] += 1  # 어느 쪽이 먼저 잠금을 얻었나에 따라 OK 또는 SESSION_REPLACED
            winner = family_of(other.json()["data"]["refresh_token"])
            if not (other.status_code == 200 and alive_families() == 1 and alive_family() == winner):
                bad_rounds.append(i + 1)
        print("   기기 1 갱신 결과:", dict(outcomes))
        good &= check("매 라운드 다른 곳 로그인 세션 1개만 생존 (기기 1의 회전 새 토큰도 끊김)", not bad_rounds)
        if bad_rounds:
            print("   실패 라운드:", bad_rounds)

        print("3) 대조군: users 잠금을 빼고 1)을 다시 → 세션이 2개 이상 살아남아야 한다")
        real_lock, real_revoke = user_repository.lock_user, user_repository.revoke_user_refresh_tokens

        async def slow_revoke(db, user_id, now, reason):
            # 폐기와 커밋 사이를 넓힌다: 모든 요청의 폐기 UPDATE가 서로의 커밋보다 먼저 실행되게
            await real_revoke(db, user_id, now, reason)
            await asyncio.sleep(0.1)

        user_repository.lock_user = user_repository.find_by_id  # 잠그지 않고 읽기만
        user_repository.revoke_user_refresh_tokens = slow_revoke
        try:
            responses = await login_all(devices)
        finally:
            user_repository.lock_user, user_repository.revoke_user_refresh_tokens = real_lock, real_revoke
        alive = alive_families()
        print("  ", dict(Counter(label(r) for r in responses)), f"살아 있는 세션 {alive}개")
        # 확률적: 10개의 비밀번호 검증(약 70ms, 스레드풀)이 끝나는 시각의 흩어짐이 0.1초보다 크면 일부만 겹친다.
        # 2개만 겹쳐도 통과이므로 실제로는 거의 항상 재현된다. 재현 실패도 '실패'로 판정한다 — 대조군이 문제를
        # 못 보여 주면 1)·2)의 통과가 잠금 덕분인지 알 수 없기 때문이다. 실패하면 다시 돌리거나 sleep을 늘린다.
        reproduced = check("잠금이 없으면 동시 로그인이 서로를 못 끊는다 (검증이 문제를 알아본다)", alive >= 2)
        if not reproduced:
            print("   (대조군은 타이밍에 기대는 확률적 재현이다. 다시 실행해 보고, 계속 실패하면 sleep을 늘린다)")
        good &= reproduced
    finally:
        for d in devices:
            await d.aclose()
    return good


def main():
    connect()
    cleanup(LOGIN)  # 이전 실행이 중간에 끊겨서 남긴 찌꺼기 제거 (사용자는 API로 새로 가입한다)
    try:
        passed = run(amain())
    finally:
        cleanup(LOGIN)
        run(engine.dispose())
    finish(passed, "통과: 동시에 로그인·갱신해도 세션은 하나만 남는다" if passed else "실패: 위 ✘ 항목을 확인한다")


if __name__ == "__main__":
    main()
