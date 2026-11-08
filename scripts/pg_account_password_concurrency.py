"""계좌 비밀번호 5회 잠금의 동시성: 같은 계좌로 틀린 계좌 비밀번호를 동시에 보내도 비밀번호는 정확히 5번만 검증되고 잠긴다.

1) 이체 20건 동시(틀린 비밀번호) → 검증 5번, 400 ACCOUNT_PASSWORD_INCORRECT 4 + 403 ACCOUNT_PASSWORD_LOCKED 16, 잠김.
   잠긴 뒤에는 맞는 비밀번호도 403.
2) 대조군: 검증 트랜잭션의 계좌 행 잠금(lock_account)을 빼면 모두 같은 옛 실패 횟수를 읽어 5번보다 많이 검증된다.
3) 계정 복구 시작(POST /recovery/start, 서로 다른 IP 20곳)도 같은 계좌 카운터를 쓴다 → 응답은 모두 같은 200,
   검증 5번, 실패 횟수 5에서 잠김. 대조군(복구의 행 잠금 제거)은 5번보다 많이 검증된다.

실행: uv run python scripts/pg_account_password_concurrency.py
"""

import asyncio
from collections import Counter

import httpx
from sqlalchemy import select

from _common import ACCOUNT_PASSWORD, check, cleanup, connect, execute, finish, make_checking, make_user, one, run, user_schema
from avengers_bank.core.database import SessionLocal, engine
from avengers_bank.core.exceptions import ApiException
from avengers_bank.core.security import DUMMY_HASH
from avengers_bank.domains.accounts import password as password_module
from avengers_bank.domains.accounts.models import CheckingAccount
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.transfers.schemas import TransferCreate
from avengers_bank.domains.transfers.service import transfer_service
from avengers_bank.main import app

LOGIN, TRIES, WRONG = "verify_account_pw", 20, "0007"
NUMS = {"A": "110-777-500001", "B": "110-777-500002"}
ids: dict[str, int] = {}
verified: list[str] = []


def reset():
    execute(
        "update checking_accounts set balance = 1000000, password_failed_count = 0, password_locked_at = null"
        " where checking_account_id = :a", a=ids["A"],
    )
    verified.clear()


def counter_state():
    return (
        one("select password_failed_count from checking_accounts where checking_account_id = :a", a=ids["A"]),
        one("select password_locked_at is not null from checking_accounts where checking_account_id = :a", a=ids["A"]),
    )


async def transfers(user, password: str, n: int) -> Counter:
    async def one_transfer():
        async with SessionLocal() as db:
            await transfer_service.transfer(
                db, TransferCreate(from_checking_account_id=ids["A"], to_account_num=NUMS["B"], amount=1000, account_password=password),
                user,
            )

    results = await asyncio.gather(*[one_transfer() for _ in range(n)], return_exceptions=True)
    return Counter("OK" if r is None else r.code if isinstance(r, ApiException) else f"ERR:{type(r).__name__}" for r in results)


async def recovery_starts(password: str) -> Counter:
    def device(n):  # 서로 다른 IP: IP 한도(15분 10번)가 아니라 계좌 카운터만 보이게
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(f"10.8.0.{n + 1}", 1234)), base_url="http://test")

    devices = [device(n) for n in range(TRIES)]
    body = {"purpose": "FIND_LOGIN_ID", "account_num": NUMS["A"], "account_password": password}
    try:
        responses = await asyncio.gather(*[d.post("/recovery/start", json=body) for d in devices])
    finally:
        for d in devices:
            await d.aclose()
    return Counter((r.status_code, r.json().get("message")) for r in responses)


async def no_lock_account(db, kind, account_id):  # 대조군: 잠그지 않고 읽은 뒤 양보해 경쟁 구간을 넓힌다
    row = await db.get(kind.model, account_id, populate_existing=True)
    await asyncio.sleep(0.05)
    return row


async def no_lock_by_num(db, account_num):
    row = await db.scalar(
        select(CheckingAccount).where(CheckingAccount.account_num == account_num).execution_options(populate_existing=True)
    )
    await asyncio.sleep(0.05)
    return row


async def amain(user):
    good = True
    real_verify = password_module.verify_password

    def counting_verify(raw, hashed):
        if hashed != DUMMY_HASH:
            verified.append(raw)
        return real_verify(raw, hashed)

    password_module.verify_password = counting_verify  # verify_account_password가 쓰는 이름만 바꾼다
    try:
        print(f"1) 같은 계좌에서 틀린 계좌 비밀번호로 이체 {TRIES}건을 동시에")
        reset()
        r = await transfers(user, WRONG, TRIES)
        print("  ", dict(r), f"검증 {len(verified)}번, 상태 {counter_state()}")
        good &= check("비밀번호 검증은 정확히 5번", len(verified) == 5)
        good &= check("400 INCORRECT 4건 + 403 LOCKED 16건",
                      r == Counter({"ACCOUNT_PASSWORD_INCORRECT": 4, "ACCOUNT_PASSWORD_LOCKED": TRIES - 4}))
        good &= check("실패 횟수 5, 잠김", counter_state() == (5, True))
        r = await transfers(user, ACCOUNT_PASSWORD, 1)
        good &= check("잠긴 뒤에는 맞는 비밀번호도 403", r == Counter({"ACCOUNT_PASSWORD_LOCKED": 1}))

        print("2) 대조군: 검증 트랜잭션의 행 잠금(lock_account)을 빼고 1)을 다시")
        reset()
        real_lock = account_repository.lock_account
        account_repository.lock_account = no_lock_account
        try:
            r = await transfers(user, WRONG, TRIES)
        finally:
            account_repository.lock_account = real_lock
        print("  ", dict(r), f"검증 {len(verified)}번 (정상은 5번)")
        good &= check("잠금이 없으면 5번보다 많이 검증된다 (검증이 문제를 알아본다)", len(verified) > 5)

        print(f"3) 계정 복구 시작을 틀린 계좌 비밀번호로 {TRIES}곳에서 동시에")
        reset()
        r = await recovery_starts(WRONG)
        print("  ", {k[0]: v for k, v in r.items()}, f"검증 {len(verified)}번, 상태 {counter_state()}")
        good &= check("응답은 모두 같은 200 (같은 문구)", len(r) == 1 and next(iter(r))[0] == 200)
        good &= check("비밀번호 검증은 정확히 5번, 실패 횟수 5에서 잠김", len(verified) == 5 and counter_state() == (5, True))

        print("4) 대조군: 복구의 행 잠금(lock_checking_by_account_num)을 빼고 3)을 다시")
        reset()
        real_by_num = account_repository.lock_checking_by_account_num
        account_repository.lock_checking_by_account_num = no_lock_by_num
        try:
            await recovery_starts(WRONG)
        finally:
            account_repository.lock_checking_by_account_num = real_by_num
        print(f"   검증 {len(verified)}번 (정상은 5번)")
        good &= check("잠금이 없으면 5번보다 많이 검증된다", len(verified) > 5)
    finally:
        password_module.verify_password = real_verify
    await engine.dispose()
    return good


def main():
    connect()
    user_id = make_user(LOGIN)
    ids["A"] = make_checking(user_id, NUMS["A"], per=10**9, daily=10**9)
    ids["B"] = make_checking(user_id, NUMS["B"], per=10**9, daily=10**9)
    try:
        passed = run(amain(user_schema(user_id, LOGIN)))
    finally:
        cleanup(LOGIN)
        print("정리 완료")
    finish(passed, "통과: 동시 요청에도 계좌 비밀번호 검증은 5번, 그 뒤 잠금" if passed else "실패: 위 ✘ 항목을 확인한다")


if __name__ == "__main__":
    main()
