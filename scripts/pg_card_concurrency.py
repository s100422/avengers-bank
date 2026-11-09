"""동시 카드 결제·청구서 (C-023): 신용 한도, 체크카드 잔액, 청구서 납부·생성의 "두 번 누름", 섞어서 동시에.
잠금을 뺀 대조군으로 이 검증이 실제 문제를 알아볼 수 있는지도 확인한다.

실행: uv run python scripts/pg_card_concurrency.py
"""

import asyncio
from collections import Counter
from datetime import timedelta

from sqlalchemy import select

from _common import (
    ACCOUNT_PASSWORD, check, cleanup, connect, execute, finish, make_checking, make_user, one, product_id, run, user_schema,
)
from avengers_bank.core.database import SessionLocal, engine
from avengers_bank.core.exceptions import ApiException
from avengers_bank.core.timezone import kst_start_utc, today_kst
from avengers_bank.domains.accounts.models import CheckingAccount
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.cards.models import CreditCardBill
from avengers_bank.domains.cards.repository import card_repository
from avengers_bank.domains.cards.schemas import BillCreate, BillPaymentCreate, CardPaymentCreate
from avengers_bank.domains.cards.service import card_service
from avengers_bank.domains.transfers.schemas import TransferCreate
from avengers_bank.domains.transfers.service import transfer_service

LOGIN = "verify_card"
state: dict = {"n": 0}


def set_balance(a=0, b=0):
    for key, value in (("A", a), ("B", b)):
        execute("update checking_accounts set balance = :v where checking_account_id = :i", v=value, i=state[key])


def balance(key="A"):
    return one("select balance from checking_accounts where checking_account_id = :i", i=state[key])


def new_credit(accumulated=0, limit=1_000_000) -> int:
    state["n"] += 1
    return one(
        "insert into credit_cards(user_id, product_id, checking_account_id, card_num, credit_limit, outstanding_amount, payment_date, status)"
        " values (:u, :p, :a, :num, :l, :acc, 14, 'ACTIVE') returning credit_card_id",
        u=state["uid"], p=state["credit_product"], a=state["A"], num=f"4000-9999-9999-{state['n']:04d}",
        l=limit, acc=accumulated,
    )


def new_debit() -> int:
    state["n"] += 1
    return one(
        "insert into debit_cards(user_id, product_id, checking_account_id, card_num, accumulated_amount, status)"
        " values (:u, :p, :a, :num, 0, 'ACTIVE') returning debit_card_id",
        u=state["uid"], p=state["debit_product"], a=state["A"], num=f"5000-9999-9999-{state['n']:04d}",
    )


def new_bill(card_id, total=500_000) -> int:
    return one(
        "insert into credit_card_bills(credit_card_id, period_start, period_end, total_amount, due_date, status)"
        " values (:c, date '2026-01-01', date '2026-01-31', :t, date '2026-02-14', 'UNPAID') returning bill_id",
        c=card_id, t=total,
    )


async def fire(factories) -> Counter:
    async def run_one(factory):
        async with SessionLocal() as db:
            return await factory(db)

    results = await asyncio.gather(*[run_one(f) for f in factories], return_exceptions=True)

    def label(r):
        if not isinstance(r, Exception):
            return "OK"
        if isinstance(r, ApiException):
            return r.code
        return "DEADLOCK" if "deadlock" in str(r).lower() else f"ERR:{type(r).__name__}"

    return Counter(label(r) for r in results)


def pay_credit(card_id, amount, user):
    return lambda db: card_service.pay(db, "credit", card_id, CardPaymentCreate(place_of_use="x", used_amount=amount), user)


def pay_debit(card_id, amount, user):
    return lambda db: card_service.pay(db, "debit", card_id, CardPaymentCreate(place_of_use="x", used_amount=amount), user)


def pay_bill(card_id, bill_id, user):
    return lambda db: card_service.pay_bill(db, card_id, bill_id, BillPaymentCreate(account_password=ACCOUNT_PASSWORD), user)


def transfer(amount, user):
    return lambda db: transfer_service.transfer(
        db, TransferCreate(
            from_checking_account_id=state["A"], to_account_num=state["B_num"], amount=amount,
            account_password=ACCOUNT_PASSWORD,
        ), user
    )


async def no_lock_card(db, kind, card_id):  # 대조군: 잠금 없이 읽는다 (읽고 쓰기 사이에 짧게 양보해 경쟁 구간을 넓힘)
    row = await db.scalar(
        select(kind.model).where(getattr(kind.model, kind.id_column) == card_id).execution_options(populate_existing=True)
    )
    await asyncio.sleep(0.01)
    return row


async def no_lock_bill(db, bill_id):
    row = await db.scalar(select(CreditCardBill).where(CreditCardBill.bill_id == bill_id).execution_options(populate_existing=True))
    await asyncio.sleep(0.01)
    return row


async def no_lock_accounts(db, ids):
    rows = list(await db.scalars(
        select(CheckingAccount).where(CheckingAccount.checking_account_id.in_(ids)).execution_options(populate_existing=True)
    ))
    await asyncio.sleep(0.01)
    return rows


def accumulated(card_table, id_column, card_id):
    return one(f"select {"outstanding_amount" if card_table == "credit_cards" else "accumulated_amount"} from {card_table} where {id_column} = :c", c=card_id)


async def amain(user):
    good = True
    real = (card_repository.lock_card, card_repository.lock_bill, account_repository.lock_checking_accounts)

    print("[a] 신용 한도 경쟁: 한도 1,000,000원 카드로 300,000원 결제 10건을 동시에")
    cid = new_credit()
    r = await fire([pay_credit(cid, 300_000, user)] * 10)
    acc = accumulated("credit_cards", "credit_card_id", cid)
    print(f"   {dict(r)} → 미결제액 {acc:,}")
    good &= check("정확히 3건 성공, 7건 한도 초과, 미결제액 900,000",
                  (r["OK"], r["CREDIT_LIMIT_EXCEEDED"], acc) == (3, 7, 900_000))

    print("[b] 체크카드 잔액 경쟁: 잔액 100,000원으로 30,000원 결제 10건을 동시에")
    set_balance(100_000)
    did = new_debit()
    r = await fire([pay_debit(did, 30_000, user)] * 10)
    acc = accumulated("debit_cards", "debit_card_id", did)
    rows = one("select count(*) from checking_account_histories where checking_account_id = :a and type = 'CARD_PAYMENT'", a=state["A"])
    print(f"   {dict(r)} → 잔액 {balance():,} / 누적 사용액 {acc:,} / 입출금 내역 {rows}건")
    good &= check("정확히 3건 성공, 잔액 10,000, 누적 90,000, 내역 3건",
                  (r["OK"], r["INSUFFICIENT_BALANCE"], balance(), acc, rows) == (3, 7, 10_000, 90_000, 3))

    print("[c] 청구서 납부 두 번 누름: 같은 청구서(500,000원)를 10건 동시에 납부")
    set_balance(2_000_000)
    cid = new_credit(accumulated=500_000)
    bid = new_bill(cid)
    r = await fire([pay_bill(cid, bid, user)] * 10)
    acc = accumulated("credit_cards", "credit_card_id", cid)
    print(f"   {dict(r)} → 잔액 {balance():,} / 미결제액 {acc:,}")
    good &= check("정확히 1건 성공, 9건 이미 납부, 출금 한 번(잔액 1,500,000), 미결제액 0",
                  (r["OK"], r["BILL_ALREADY_PAID"], balance(), acc) == (1, 9, 1_500_000, 0))

    print("[d] 청구서 생성 두 번 누름: 같은 달 청구서를 10건 동시에 생성")
    last_start = (today_kst().replace(day=1) - timedelta(days=1)).replace(day=1)
    cid = new_credit(accumulated=300_000)
    for amount, hours in ((100_000, 12), (200_000, 36)):
        execute(
            "insert into credit_card_histories(credit_card_id, place_of_use, used_amount, time) values (:c, 'x', :a, :t)",
            c=cid, a=amount, t=kst_start_utc(last_start) + timedelta(hours=hours),
        )
    year_month = last_start.strftime("%Y-%m")
    r = await fire([lambda db: card_service.create_bill(db, cid, BillCreate(year_month=year_month), user)] * 10)
    bills = one("select count(*) from credit_card_bills where credit_card_id = :c", c=cid)
    unbilled = one("select count(*) from credit_card_histories where credit_card_id = :c and bill_id is null", c=cid)
    print(f"   {dict(r)} → 청구서 {bills}개 / 미청구 내역 {unbilled}건")
    good &= check("정확히 1건 성공, 9건 이미 있음, 청구서 1개, 모든 내역이 청구됨",
                  (r["OK"], r["BILL_ALREADY_EXISTS"], bills, unbilled) == (1, 9, 1, 0))

    print("[e] 섞어서 동시에: 같은 계좌에서 체크 결제 10건 + 이체 10건 + 청구서 납부 1건")
    set_balance(2_000_000, 0)
    did = new_debit()
    cid = new_credit(accumulated=500_000)
    bid = new_bill(cid)
    r = await fire([pay_debit(did, 10_000, user)] * 10 + [transfer(10_000, user)] * 10 + [pay_bill(cid, bid, user)])
    acc = accumulated("credit_cards", "credit_card_id", cid)
    print(f"   {dict(r)} → A {balance():,} / B {balance('B'):,} / 청구 미결제액 {acc:,}")
    good &= check("21건 모두 성공, 데드락 없음, A=1,300,000 B=100,000(금액 보존)",
                  (r["OK"], balance(), balance("B"), acc) == (21, 1_300_000, 100_000, 0))

    print("[대조군 a] 카드 행을 잠그지 않고 [a]를 다시")
    card_repository.lock_card = no_lock_card
    try:
        cid = new_credit()
        r = await fire([pay_credit(cid, 300_000, user)] * 10)
    finally:
        card_repository.lock_card = real[0]
    acc = accumulated("credit_cards", "credit_card_id", cid)
    print(f"   {dict(r)} → 미결제액 {acc:,} (한도 1,000,000)")
    control_a = r["OK"] > 3

    print("[대조군 c] 계좌·카드·청구서를 잠그지 않고 [c]를 다시")
    card_repository.lock_card, card_repository.lock_bill = no_lock_card, no_lock_bill
    account_repository.lock_checking_accounts = no_lock_accounts
    try:
        set_balance(2_000_000)
        cid = new_credit(accumulated=500_000)
        bid = new_bill(cid)
        r = await fire([pay_bill(cid, bid, user)] * 10)
    finally:
        card_repository.lock_card, card_repository.lock_bill, account_repository.lock_checking_accounts = real
    print(f"   {dict(r)} → 같은 청구서에 '납부 성공' {r['OK']}건 (정상은 1건)")
    control_c = r["OK"] > 1

    await engine.dispose()
    return good, control_a, control_c


def main():
    connect()
    state["uid"] = make_user(LOGIN)
    big = {"per": 1_000_000_000, "daily": 1_000_000_000}  # 이체 한도에 걸리지 않게 (시나리오 e의 이체)
    state["A"] = make_checking(state["uid"], "110-777-300001", **big)
    state["B"] = make_checking(state["uid"], "110-777-300002", **big)
    state["B_num"] = "110-777-300002"
    state["credit_product"] = product_id("card_products", "CREDIT")
    state["debit_product"] = product_id("card_products", "DEBIT")
    try:
        good, control_a, control_c = run(amain(user_schema(state["uid"], LOGIN)))
    finally:
        cleanup(LOGIN)
        print("정리 완료")
    passed = good and control_a and control_c
    finish(passed, f"검증 결과: {'통과' if passed else '실패'} (현재 코드 정상={good}, 대조군 a 문제 재현={control_a}, 대조군 c 문제 재현={control_c})")


if __name__ == "__main__":
    main()
