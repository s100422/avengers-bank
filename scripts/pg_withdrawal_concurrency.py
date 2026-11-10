"""회원 탈퇴 ↔ 남이 그 계좌로 입금 (동시): 어느 쪽이 먼저든 '탈퇴했는데 계좌에 돈이 남은' 상태가 없어야 한다.

탈퇴는 users → 입출금 계좌(FOR UPDATE)를 잠그고 '잔액 0 확인 → closed_at', 이체는 두 입출금 계좌를 잠근 뒤 closed_at을
확인한다(accounts/service.py require_open). 같은 행을 잠그므로 둘은 한 줄로 선다:
- 이체가 먼저 → 탈퇴는 잔액 > 0을 보고 WITHDRAWAL_BLOCKED
- 탈퇴가 먼저 → 이체는 닫힌 계좌를 보고 404 ACCOUNT_NOT_FOUND ("받는 계좌를 찾을 수 없습니다.")
대조군: 입출금 계좌 잠금(lock_checking_accounts)을 '잠그지 않고 읽기'로 바꾸면 둘 다 성공해 돈이 남는다.

실행 (마이그레이션 8d9e0f1a2b3c 적용 뒤): uv run python scripts/pg_withdrawal_concurrency.py
"""

import asyncio
import random
from collections import Counter
from datetime import datetime, timezone

import jwt
from sqlalchemy import select

from _common import (
    ACCOUNT_PASSWORD, check, cleanup, connect, execute, finish, make_checking, make_user, one, run, user_schema,
)
from avengers_bank.core.config import get_settings
from avengers_bank.core.database import SessionLocal, engine
from avengers_bank.core.exceptions import ApiException
from avengers_bank.core.security import ALGORITHM, hash_password
from avengers_bank.domains.accounts.models import CheckingAccount
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.transfers.schemas import TransferCreate
from avengers_bank.domains.transfers.service import transfer_service
from avengers_bank.domains.users import withdrawal
from avengers_bank.domains.verification.service import TOKEN_TTL, TOKEN_TYPE

LEAVER, SENDER = "verify_withdrawal_w", "verify_withdrawal_s"
NUMS = {"W": "110-777-400001", "S": "110-777-400002"}
PASSWORD = "Passw0rd!23"
ROUNDS = 20
ids: dict[str, int] = {}


def reset(password_hash: str) -> None:
    """탈퇴할 사람을 매 라운드 '탈퇴 전, 잔액 0' 상태로 되돌린다."""
    execute("delete from account_notifications where checking_account_history_id in (select checking_account_history_id from checking_account_histories where checking_account_id in (:w, :s))", w=ids["W"], s=ids["S"])
    execute("delete from checking_account_histories where checking_account_id in (:w, :s)", w=ids["W"], s=ids["S"])
    execute("update checking_accounts set balance = 0, closed_at = null where checking_account_id = :w", w=ids["W"])
    execute("update checking_accounts set balance = 1000000 where checking_account_id = :s", s=ids["S"])
    execute(
        "update users set deleted_at = null, name = 't', phone = '010', hashed_password = :h, failed_login_count = 0,"
        " login_locked_at = null where user_id = :u", h=password_hash, u=ids["leaver"],
    )


def withdrawal_token() -> str:
    """확인까지 끝난 WITHDRAWAL 인증번호 행 + 증표 (verify_code와 같은 모양). 문자 발송 제한을 피하려고 SQL로 만든다."""
    vid = one(
        "insert into verification_codes(purpose, phone, user_id, code_hash, attempts, expires_at, verified_at)"
        " values ('WITHDRAWAL', '010', :u, 'x', 1, now() + interval '10 minutes', now()) returning verification_id",
        u=ids["leaver"],
    )
    now = datetime.now(timezone.utc)
    payload = {"typ": TOKEN_TYPE, "vid": vid, "purpose": "WITHDRAWAL", "phone": "010", "uid": ids["leaver"],
               "iat": now, "exp": now + TOKEN_TTL}
    return jwt.encode(payload, get_settings().jwt_secret_key.get_secret_value(), algorithm=ALGORITHM)


def label(result) -> str:
    if result is None:
        return "OK"
    if isinstance(result, ApiException):
        return result.code
    return "DEADLOCK" if "deadlock" in str(result).lower() else f"ERR:{type(result).__name__}:{result}"


async def one_round(leaver, sender, token):
    async def leave():
        async with SessionLocal() as db:
            await withdrawal.withdraw(db, leaver, PASSWORD, token)

    async def send():
        await asyncio.sleep(random.uniform(0, 0.1))  # 어느 쪽이 먼저 잠그는지 라운드마다 달라지게
        async with SessionLocal() as db:
            data = TransferCreate(from_checking_account_id=ids["S"], to_account_num=NUMS["W"], amount=1_000,
                                  account_password=ACCOUNT_PASSWORD)
            await transfer_service.transfer(db, data, sender)

    w, s = await asyncio.gather(leave(), send(), return_exceptions=True)
    deleted = one("select deleted_at is not null from users where user_id = :u", u=ids["leaver"])
    balance = one("select balance from checking_accounts where checking_account_id = :w", w=ids["W"])
    return label(w), label(s), deleted, balance


async def rounds(leaver, sender, password_hash) -> tuple[Counter, int]:
    outcomes, stranded = Counter(), 0
    for _ in range(ROUNDS):
        reset(password_hash)
        w, s, deleted, balance = await one_round(leaver, sender, withdrawal_token())
        outcomes[(w, s)] += 1
        stranded += bool(deleted and balance > 0)  # 탈퇴했는데 돈이 남았다
    return outcomes, stranded


async def no_lock(db, ids_):  # 대조군: 잠그지 않고 읽고, 읽은 뒤 양보해 상대가 같은 '옛 값'을 읽게 한다
    rows = list(await db.scalars(
        select(CheckingAccount).where(CheckingAccount.checking_account_id.in_(ids_))
        .order_by(CheckingAccount.checking_account_id).execution_options(populate_existing=True)
    ))
    await asyncio.sleep(0.2)
    return rows


async def amain(leaver, sender, password_hash):
    print(f"[1] 탈퇴(잔액 0) ↔ 남이 그 계좌로 1,000원 이체를 동시에 {ROUNDS}번")
    outcomes, stranded = await rounds(leaver, sender, password_hash)
    for (w, s), n in outcomes.items():
        print(f"   탈퇴={w}, 이체={s}: {n}번")
    allowed = {("OK", "ACCOUNT_NOT_FOUND"), ("WITHDRAWAL_BLOCKED", "OK")}
    good = check("탈퇴했는데 돈이 남은 라운드 0번", stranded == 0)
    good &= check("결과는 (탈퇴 성공, 이체 404) 또는 (탈퇴 막힘, 이체 성공)뿐 — 데드락·서버 오류 없음", set(outcomes) <= allowed)

    print("[대조군] 입출금 계좌 잠금을 빼고 [1]을 다시")
    real = account_repository.lock_checking_accounts
    account_repository.lock_checking_accounts = no_lock
    try:
        outcomes, control_stranded = await rounds(leaver, sender, password_hash)
    finally:
        account_repository.lock_checking_accounts = real
    for (w, s), n in outcomes.items():
        print(f"   탈퇴={w}, 이체={s}: {n}번")
    print(f"   탈퇴했는데 돈이 남은 라운드: {control_stranded}번 (정상은 0)")
    await engine.dispose()
    return good, control_stranded > 0


def main():
    connect()
    ids["leaver"] = make_user(LEAVER)
    ids["sender"] = make_user(SENDER)
    ids["W"] = make_checking(ids["leaver"], NUMS["W"])
    ids["S"] = make_checking(ids["sender"], NUMS["S"], per=1_000_000, daily=100_000_000)
    password_hash = hash_password(PASSWORD)
    try:
        good, control = run(amain(user_schema(ids["leaver"], LEAVER), user_schema(ids["sender"], SENDER), password_hash))
    finally:
        cleanup(LEAVER)
        cleanup(SENDER)
        print("정리 완료")
    passed = good and control
    finish(passed, f"검증 결과: {'통과' if passed else '실패'} (현재 코드 정상={good}, 대조군 문제 재현={control})")


if __name__ == "__main__":
    main()
