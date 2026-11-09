"""동시 이체 (C-022): 잔액·1일 한도가 동시 요청에서도 지켜지고, A→B / B→A가 데드락 없이 끝난다.
잠금을 뺀 대조군으로 이 검증이 실제 문제를 알아볼 수 있는지도 확인한다.

실행: uv run python scripts/pg_transfer_concurrency.py
"""

import asyncio
from collections import Counter

from sqlalchemy import select

from _common import ACCOUNT_PASSWORD, check, cleanup, connect, execute, finish, make_checking, make_user, one, run, user_schema
from avengers_bank.core.database import SessionLocal, engine
from avengers_bank.core.exceptions import ApiException
from avengers_bank.domains.accounts.models import CheckingAccount
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.transfers.schemas import TransferCreate
from avengers_bank.domains.transfers.service import transfer_service

LOGIN = "verify_transfer"
NUMS = {"A": "110-777-200001", "B": "110-777-200002"}
ids: dict[str, int] = {}


def reset(bal_a, bal_b, per, daily):
    execute("delete from checking_account_histories where checking_account_id in (:a, :b)", a=ids["A"], b=ids["B"])
    for key, balance in (("A", bal_a), ("B", bal_b)):
        execute(
            "update checking_accounts set balance = :v, per_transfer_limit = :p, daily_transfer_limit = :d"
            " where checking_account_id = :i", v=balance, p=per, d=daily, i=ids[key],
        )


def balances():
    return tuple(one("select balance from checking_accounts where checking_account_id = :i", i=ids[k]) for k in "AB")


async def fire(user, jobs) -> Counter:
    """jobs: [(보내는 쪽, 받는 쪽, 금액)]을 동시에 보내고 결과를 종류별로 센다."""
    async def one_transfer(src, dst, amount):
        async with SessionLocal() as db:
            await transfer_service.transfer(
                db, TransferCreate(
                    from_checking_account_id=ids[src], to_account_num=NUMS[dst], amount=amount,
                    account_password=ACCOUNT_PASSWORD,
                ), user
            )

    results = await asyncio.gather(*[one_transfer(*j) for j in jobs], return_exceptions=True)

    def label(r):
        if r is None:
            return "OK"
        if isinstance(r, ApiException):
            return r.code
        return "DEADLOCK" if "deadlock" in str(r).lower() else f"ERR:{type(r).__name__}"

    return Counter(label(r) for r in results)


async def no_lock(db, ids_):  # 대조군: 잠금 없이 읽는다 (읽고 쓰기 사이에 짧게 양보해 경쟁 구간을 넓힘)
    rows = list(await db.scalars(
        select(CheckingAccount).where(CheckingAccount.checking_account_id.in_(ids_)).execution_options(populate_existing=True)
    ))
    await asyncio.sleep(0.01)
    return rows


async def naive_lock(db, ids_):  # 대조군: 받은 순서(보내는 계좌 먼저)대로 하나씩 따로 잠근다
    rows = []
    for i in ids_:
        rows += list(await db.scalars(
            select(CheckingAccount).where(CheckingAccount.checking_account_id == i)
            .with_for_update().execution_options(populate_existing=True)
        ))
        await asyncio.sleep(0.05)
    return rows


async def amain(user):
    good = True
    real = account_repository.lock_checking_accounts

    print("[1] 잔액 경쟁: A 잔액 100,000원에서 30,000원 이체 10건을 동시에")
    reset(100_000, 0, 1_000_000, 5_000_000)
    r = await fire(user, [("A", "B", 30_000)] * 10)
    a, b = balances()
    print(f"   {dict(r)} → A={a:,} B={b:,}")
    good &= check("정확히 3건 성공, 7건 잔액 부족, A=10,000 B=90,000",
                  (r["OK"], r["INSUFFICIENT_BALANCE"], a, b) == (3, 7, 10_000, 90_000))

    print("[2] 1일 한도 경쟁: 한도 300,000원(1회 100,000원)에서 100,000원 이체 10건을 동시에")
    reset(1_000_000, 0, 100_000, 300_000)
    r = await fire(user, [("A", "B", 100_000)] * 10)
    a, b = balances()
    print(f"   {dict(r)} → A={a:,} B={b:,}")
    good &= check("정확히 3건 성공, 7건 한도 초과, A=700,000 B=300,000",
                  (r["OK"], r["DAILY_LIMIT_EXCEEDED"], a, b) == (3, 7, 700_000, 300_000))

    print("[3] 데드락: A→B 10건과 B→A 10건을 동시에 (각 1,000원)")
    reset(1_000_000, 1_000_000, 1_000_000, 5_000_000)
    r = await fire(user, [("A", "B", 1000)] * 10 + [("B", "A", 1000)] * 10)
    a, b = balances()
    print(f"   {dict(r)} → A={a:,} B={b:,}")
    good &= check("20건 모두 성공, 데드락 없음, 합계 보존(A=B=1,000,000)",
                  (r["OK"], r["DEADLOCK"], a, b) == (20, 0, 1_000_000, 1_000_000) and sum(r.values()) == 20)

    print("[대조군 1] 잠금 없이 [1]을 다시")
    account_repository.lock_checking_accounts = no_lock
    try:
        reset(100_000, 0, 1_000_000, 5_000_000)
        r = await fire(user, [("A", "B", 30_000)] * 10)
        a, b = balances()
    finally:
        account_repository.lock_checking_accounts = real
    print(f"   {dict(r)} → A={a:,} B={b:,} (정상은 3건 성공)")
    control1 = r["OK"] > 3

    print("[대조군 2] 잠금 순서를 고정하지 않고 [3]을 다시")
    account_repository.lock_checking_accounts = naive_lock
    try:
        reset(1_000_000, 1_000_000, 1_000_000, 5_000_000)
        r = await fire(user, [("A", "B", 1000)] * 10 + [("B", "A", 1000)] * 10)
    finally:
        account_repository.lock_checking_accounts = real
    print(f"   {dict(r)}")
    control2 = r["DEADLOCK"] > 0

    await engine.dispose()
    return good, control1, control2


def main():
    connect()
    user_id = make_user(LOGIN)
    ids["A"] = make_checking(user_id, NUMS["A"])
    ids["B"] = make_checking(user_id, NUMS["B"])
    try:
        good, control1, control2 = run(amain(user_schema(user_id, LOGIN)))
    finally:
        cleanup(LOGIN)
        print("정리 완료")
    passed = good and control1 and control2
    finish(passed, f"검증 결과: {'통과' if passed else '실패'} (현재 코드 정상={good}, 대조군1 문제 재현={control1}, 대조군2 데드락 재현={control2})")


if __name__ == "__main__":
    main()
