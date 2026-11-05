"""동시 해지 (C-043): 같은 예금을 여러 번 동시에 해지해도 한 번만 돈이 나가고,
해지와 동시에 들어오는 입금이 해지된 계좌에 남지 않는다. 잠금을 뺀 대조군으로 이 검증이 실제 문제를 알아본다.

실행: uv run python scripts/pg_close_concurrency.py
"""

import asyncio
from collections import Counter
from datetime import date, timedelta

from sqlalchemy import select

from _common import check, cleanup, connect, execute, finish, make_checking, make_user, one, product_id, run, user_schema
from avengers_bank.core.database import SessionLocal, engine
from avengers_bank.core.exceptions import ApiException
from avengers_bank.domains.accounts.models import CheckingAccount
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.accounts.schemas import AccountCloseRequest
from avengers_bank.domains.accounts.service import account_service
from avengers_bank.domains.transfers.schemas import DepositPaymentCreate
from avengers_bank.domains.transfers.service import transfer_service

LOGIN = "verify_close"
CHECKING_START, DEPOSIT_START = 1_000_000, 300_000
ids: dict[str, int] = {}


def reset():
    execute("delete from checking_account_histories where checking_account_id = :c", c=ids["checking"])
    execute("delete from deposit_account_histories where deposit_account_id = :d", d=ids["deposit"])
    execute("update checking_accounts set balance = :b where checking_account_id = :c", b=CHECKING_START, c=ids["checking"])
    execute(
        "update deposit_accounts set balance = :b, status = 'ACTIVE', closed_at = null where deposit_account_id = :d",
        b=DEPOSIT_START, d=ids["deposit"],
    )


def state():
    checking = one("select balance from checking_accounts where checking_account_id = :c", c=ids["checking"])
    deposit = one("select balance from deposit_accounts where deposit_account_id = :d", d=ids["deposit"])
    status = one("select status from deposit_accounts where deposit_account_id = :d", d=ids["deposit"])
    return checking, deposit, status


def label(r):
    if r is None:
        return "OK"
    if isinstance(r, ApiException):
        return r.code
    return "DEADLOCK" if "deadlock" in str(r).lower() else f"ERR:{type(r).__name__}"


async def close(user, delay=0.0):
    await asyncio.sleep(delay)
    async with SessionLocal() as db:
        await account_service.close_account(
            db, "deposit", ids["deposit"], AccountCloseRequest(to_checking_account_id=ids["checking"]), user
        )


async def deposit(user):
    async with SessionLocal() as db:
        await transfer_service.pay_deposit(
            db, DepositPaymentCreate(from_checking_account_id=ids["checking"], deposit_account_id=ids["deposit"], amount=1000), user
        )


async def no_lock_checking(db, ids_):  # 대조군: 잠금 없이 읽고, 읽은 뒤 잠깐 양보해 경쟁 구간을 넓힌다
    rows = list(await db.scalars(
        select(CheckingAccount).where(CheckingAccount.checking_account_id.in_(ids_)).execution_options(populate_existing=True)
    ))
    await asyncio.sleep(0.05)
    return rows


async def no_lock_account(db, kind, account_id):
    row = await db.get(kind.model, account_id, populate_existing=True)
    await asyncio.sleep(0.05)
    return row


async def amain(user):
    good = True
    real_checking, real_account = account_repository.lock_checking_accounts, account_repository.lock_account
    expected_checking = CHECKING_START + DEPOSIT_START

    print("1) 같은 예금을 20번 동시에 해지 (잠금 있음)")
    reset()
    results = Counter(label(r) for r in await asyncio.gather(*[close(user) for _ in range(20)], return_exceptions=True))
    checking, deposit_balance, status = state()
    print("  ", dict(results), "입출금 잔액:", checking)
    good &= check("정확히 한 번만 해지되고 나머지는 ACCOUNT_CLOSED", results == Counter({"OK": 1, "ACCOUNT_CLOSED": 19}))
    good &= check("해지금이 한 번만 입출금 계좌에 들어갔다", (checking, deposit_balance, status) == (expected_checking, 0, "CLOSED"))

    print("2) 해지 1번 + 입금 20번을 섞어서 동시에 (잠금 있음)")
    reset()
    jobs = [close(user, delay=0.03)] + [deposit(user) for _ in range(20)]  # 입금이 먼저 들어가는 중에 해지가 끼어든다
    jobs.insert(10, close(user, delay=0.03))
    results = Counter(label(r) for r in await asyncio.gather(*jobs, return_exceptions=True))
    checking, deposit_balance, status = state()
    print("  ", dict(results), "입출금 잔액:", checking, "예금 잔액:", deposit_balance)
    good &= check("데드락·예상 밖 오류가 없다", set(results) <= {"OK", "ACCOUNT_CLOSED"})
    good &= check("해지된 계좌에 돈이 남지 않고 돈의 합계가 그대로", (checking, deposit_balance, status) == (expected_checking, 0, "CLOSED"))

    print("3) 대조군: 잠금 없이 같은 예금을 20번 동시에 해지 → 중복 지급이 재현돼야 한다")
    reset()
    account_repository.lock_checking_accounts, account_repository.lock_account = no_lock_checking, no_lock_account
    try:
        results = Counter(label(r) for r in await asyncio.gather(*[close(user) for _ in range(20)], return_exceptions=True))
    finally:
        account_repository.lock_checking_accounts, account_repository.lock_account = real_checking, real_account
    checking, _, _ = state()
    print("  ", dict(results), "입출금 잔액:", checking, f"(정상이면 {expected_checking})")
    good &= check("잠금이 없으면 해지가 여러 번 성공한다 (검증이 문제를 알아본다)", results["OK"] > 1)
    return good


def main():
    connect()
    user_id = make_user(LOGIN)
    try:
        ids["checking"] = make_checking(user_id, "110-777-300001", CHECKING_START, per=10**9, daily=10**9)
        ids["deposit"] = one(
            "insert into deposit_accounts(user_id, product_id, account_num, balance, maturity_date, status)"
            " values (:u, :p, '120-777-300001', :b, :m, 'ACTIVE') returning deposit_account_id",
            u=user_id, p=product_id("account_products", "DEPOSIT"), b=DEPOSIT_START, m=date.today() + timedelta(days=365),
        )
        passed = run(amain(user_schema(user_id, LOGIN)))
    finally:
        cleanup(LOGIN)
        run(engine.dispose())
    finish(passed, "통과: 동시 해지에서도 돈이 한 번만 움직인다" if passed else "실패: 위 ✘ 항목을 확인한다")


if __name__ == "__main__":
    main()
