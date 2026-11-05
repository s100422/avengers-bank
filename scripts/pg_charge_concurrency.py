"""동시 충전 30건 (C-021): 잠금이 있으면 합계가 맞고, 잠금을 빼면 갱신이 사라진다.

실행: uv run python scripts/pg_charge_concurrency.py
"""

import asyncio

from sqlalchemy import select

from _common import check, cleanup, connect, execute, finish, make_checking, make_user, one, run, user_schema
from avengers_bank.core.database import SessionLocal, engine
from avengers_bank.domains.accounts import dev
from avengers_bank.domains.accounts.models import CheckingAccount
from avengers_bank.domains.accounts.repository import account_repository

LOGIN, N, AMOUNT = "verify_charge", 30, 1000


async def charge_all(user, account_id):
    async def charge_once():
        async with SessionLocal() as db:
            await dev.charge_checking(db, account_id, AMOUNT, user)

    await asyncio.gather(*[charge_once() for _ in range(N)])


def result(account_id):
    q = "from checking_account_histories where checking_account_id = :a"
    balance = one("select balance from checking_accounts where checking_account_id = :a", a=account_id)
    return balance, one(f"select count(*) {q}", a=account_id), one(f"select count(distinct balance_after) {q}", a=account_id)


async def without_lock(db, ids):  # 대조군: 잠금 없이 읽는다 (읽고 쓰기 사이에 짧게 양보해 경쟁 구간을 넓힘)
    rows = list(await db.scalars(
        select(CheckingAccount).where(CheckingAccount.checking_account_id.in_(ids)).execution_options(populate_existing=True)
    ))
    await asyncio.sleep(0.01)
    return rows


async def amain(user, account_id):
    expected = N * AMOUNT
    print(f"[잠금 사용] 1,000원 충전 {N}건을 동시에")
    await charge_all(user, account_id)
    balance, rows, distinct = result(account_id)
    print(f"   기대 잔액 {expected:,} / 실제 잔액 {balance:,} / 거래내역 {rows}건 / balance_after {distinct}종류")
    ok = check("한 건도 안 사라졌고 balance_after가 모두 다름", (balance, rows, distinct) == (expected, N, N))

    execute("delete from checking_account_histories where checking_account_id = :a", a=account_id)
    execute("update checking_accounts set balance = 0 where checking_account_id = :a", a=account_id)
    print("[대조군] 잠금 없이 같은 요청")
    real = account_repository.lock_checking_accounts
    account_repository.lock_checking_accounts = without_lock
    try:
        await charge_all(user, account_id)
    finally:
        account_repository.lock_checking_accounts = real
    balance, rows, _ = result(account_id)
    print(f"   기대 잔액 {expected:,} / 실제 잔액 {balance:,} / 거래내역 {rows}건")
    control = balance != expected
    print(f"   → {'충전 ' + str(rows) + '건이 성공했는데 ' + format(expected - balance, ',') + '원이 사라짐 (갱신 손실)' if control else '손실 없음 (대조군이 경쟁을 만들지 못함)'}")
    await engine.dispose()
    return ok, control


def main():
    connect()
    user_id = make_user(LOGIN)
    account_id = make_checking(user_id, "110-777-100001")
    try:
        ok, control = run(amain(user_schema(user_id, LOGIN), account_id))
    finally:
        cleanup(LOGIN)
        print("정리 완료")
    finish(ok and control, f"검증 결과: {'통과' if ok and control else '실패'} (잠금 정상={ok}, 대조군 손실 재현={control})")


if __name__ == "__main__":
    main()
