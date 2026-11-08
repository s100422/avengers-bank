"""동시 예금 가입 (C-076): 같은 입출금 계좌에서 가입 금액을 내는 예금 가입을 동시에 여러 번 보내도
잔액만큼만 가입되고 돈의 합계가 그대로다. 잠금을 뺀 대조군으로 이 검증이 실제 문제를 알아본다.

실제 API(POST /accounts/deposit)를 ASGI로 직접 부르므로 약관 동의·최소 금액·개설·이체가 한 트랜잭션인 것까지 같이 본다.
먼저 약관이 발행돼 있어야 한다 (terms.publish).

실행: uv run python scripts/pg_deposit_open_concurrency.py
"""

import asyncio
from collections import Counter
from datetime import date, timedelta

import httpx
from sqlalchemy import select

from _common import check, cleanup, connect, execute, finish, make_checking, one, run
from avengers_bank.core.database import engine
from avengers_bank.domains.accounts.models import CheckingAccount
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.main import app

LOGIN = "verify_open"
START, AMOUNT, TRIES = 1_000_000, 100_000, 20  # 잔액으로 정확히 10건만 가능
ids: dict[str, int] = {}


def clear():
    """시나리오 사이에 가입된 예금과 거래내역·동의 기록을 지우고 잔액을 되돌린다."""
    u = ids["user"]
    execute("delete from terms_consents where user_id = :u", u=u)
    execute("delete from deposit_account_histories where deposit_account_id in (select deposit_account_id from deposit_accounts where user_id = :u)", u=u)
    execute("delete from deposit_accounts where user_id = :u", u=u)
    execute("delete from checking_account_histories where checking_account_id = :c", c=ids["checking"])
    execute("update checking_accounts set balance = :b where checking_account_id = :c", b=START, c=ids["checking"])


def state():
    checking = one("select balance from checking_accounts where checking_account_id = :c", c=ids["checking"])
    count = one("select count(*) from deposit_accounts where user_id = :u", u=ids["user"])
    total = one("select coalesce(sum(balance), 0) from deposit_accounts where user_id = :u", u=ids["user"])
    consents = one("select count(distinct subject_id) from terms_consents where user_id = :u and subject_kind = 'deposit'", u=ids["user"])
    return checking, count, total, consents


async def no_lock_checking(db, ids_):  # 대조군: 잠금 없이 읽고, 읽은 뒤 잠깐 양보해 경쟁 구간을 넓힌다
    rows = list(await db.scalars(
        select(CheckingAccount).where(CheckingAccount.checking_account_id.in_(ids_)).execution_options(populate_existing=True)
    ))
    await asyncio.sleep(0.05)
    return rows


async def open_all(client, headers, body):
    responses = await asyncio.gather(*[client.post("/accounts/deposit", json=body, headers=headers) for _ in range(TRIES)])
    return Counter("OK" if r.status_code == 201 else r.json().get("error", {}).get("code", r.status_code) for r in responses)


async def amain():
    good = True
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        body = {"login_id": LOGIN, "password": "password1234", "name": "검증", "phone": "010-0000-0000"}
        assert (await client.post("/users/signup", json=body)).status_code == 201
        token = (await client.post("/users/login", json={"login_id": LOGIN, "password": "password1234"})).json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        ids["user"] = one("select user_id from users where login_id = :l", l=LOGIN)
        ids["checking"] = make_checking(ids["user"], "110-777-400001", START, per=10**9, daily=10**9)

        product = one("select product_id from account_products where type = 'DEPOSIT' and min_amount is not null and min_amount <= :a order by 1 limit 1", a=AMOUNT)
        terms = (await client.get(f"/terms/products/deposit/{product}")).json()["data"]
        request = {
            "product_id": product, "maturity_date": (date.today() + timedelta(days=365)).isoformat(),
            "initial_amount": AMOUNT, "from_checking_account_id": ids["checking"],
            "terms": {
                "revision_id": terms["revision_id"], "set_hash": terms["set_hash"],
                "agreements": [{"terms_version_id": i["terms_version_id"], "agreed": True} for i in terms["items"]],
            },
        }

        print(f"1) 잔액 {START:,}원에서 {AMOUNT:,}원짜리 예금 가입을 {TRIES}번 동시에 (잠금 있음)")
        clear()
        results = await open_all(client, headers, request)
        checking, count, total, consents = state()
        print("  ", dict(results), "입출금 잔액:", checking, "예금 수:", count, "예금 합계:", total)
        good &= check("정확히 잔액만큼(10건)만 가입되고 나머지는 INSUFFICIENT_BALANCE", results == Counter({"OK": 10, "INSUFFICIENT_BALANCE": 10}))
        good &= check("돈의 합계가 그대로이고 입출금 잔액은 0원", (checking, total) == (0, START) and checking + total == START)
        good &= check("실패한 가입은 예금도 약관 동의 기록도 남기지 않았다 (동의 기록 10건 = 예금 10개)", (count, consents) == (10, 10))

        print("2) 대조군: 잠금 없이 같은 가입을 동시에 → 잔액보다 많이 가입돼 돈이 늘어나야 한다")
        clear()
        real = account_repository.lock_checking_accounts
        account_repository.lock_checking_accounts = no_lock_checking
        try:
            results = await open_all(client, headers, request)
        finally:
            account_repository.lock_checking_accounts = real
        checking, count, total, _ = state()
        print("  ", dict(results), "입출금 잔액:", checking, "예금 합계:", total, f"(정상이면 합계 {START})")
        good &= check("잠금이 없으면 잔액보다 많이 가입된다 (검증이 문제를 알아본다)", results["OK"] > 10 or checking + total != START)
    return good


def main():
    connect()
    cleanup(LOGIN)  # 이전 실행이 중간에 끊겨서 남긴 찌꺼기 제거 (사용자는 API로 새로 가입한다)
    try:
        passed = run(amain())
    finally:
        cleanup(LOGIN)
        run(engine.dispose())
    finish(passed, "통과: 동시 가입에서도 잔액만큼만 가입되고 돈이 그대로다" if passed else "실패: 위 ✘ 항목을 확인한다")


if __name__ == "__main__":
    main()
