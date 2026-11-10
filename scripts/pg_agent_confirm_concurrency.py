"""AI 이체 초안 동시 확인 (C-070): 같은 초안을 10번 동시에 확인해도 이체는 한 번만 된다.
상태 조건 없이 바꾸는 대조군으로 이 검증이 이중 이체를 알아볼 수 있는지도 확인한다.

실행: uv run python scripts/pg_agent_confirm_concurrency.py
"""

import asyncio
import secrets
from collections import Counter

from sqlalchemy import update

from _common import ACCOUNT_PASSWORD, check, cleanup, connect, execute, finish, make_checking, make_user, one, run, user_schema
from avengers_bank.core.database import SessionLocal, engine
from avengers_bank.core.exceptions import ApiException
from avengers_bank.domains.agent.models import TransferDraft
from avengers_bank.domains.agent.repository import agent_repository
from avengers_bank.domains.agent.service import agent_service

LOGIN = "verify_agent_confirm"
NUMS = {"A": "110-777-300001", "B": "110-777-300002"}
ids: dict[str, int] = {}
AMOUNT = 10_000


def new_draft(user_id: int) -> str:
    """잔액·이력을 초기화하고 PENDING 초안 하나를 만든다."""
    execute("delete from account_notifications where checking_account_history_id in (select checking_account_history_id from checking_account_histories where checking_account_id in (:a, :b))", a=ids["A"], b=ids["B"])
    execute("delete from checking_account_histories where checking_account_id in (:a, :b)", a=ids["A"], b=ids["B"])
    execute("update checking_accounts set balance = 1000000 where checking_account_id = :a", a=ids["A"])
    execute("update checking_accounts set balance = 0 where checking_account_id = :b", b=ids["B"])
    draft_id = secrets.token_urlsafe(32)
    execute(
        "insert into agent_transfer_drafts(draft_id, user_id, from_checking_account_id, to_account_num, recipient_name,"
        " amount, status, expires_at) values (:d, :u, :f, :t, 't', :amt, 'PENDING', now() + interval '5 minutes')",
        d=draft_id, u=user_id, f=ids["A"], t=NUMS["B"], amt=AMOUNT,
    )
    return draft_id


async def fire(user, draft_id: str, n: int = 10) -> Counter:
    async def confirm():
        async with SessionLocal() as db:
            await agent_service.confirm_draft(db, draft_id, ACCOUNT_PASSWORD, user)

    results = await asyncio.gather(*[confirm() for _ in range(n)], return_exceptions=True)
    return Counter("OK" if r is None else r.code if isinstance(r, ApiException) else f"ERR:{type(r).__name__}" for r in results)


def moved() -> tuple[int, int]:
    b = one("select balance from checking_accounts where checking_account_id = :i", i=ids["B"])
    outs = one("select count(*) from checking_account_histories where checking_account_id = :i and type = 'TRANSFER_OUT'", i=ids["A"])
    return b, outs


async def naive_transition(db, draft_id, user_id, to_status, now, *, require_unexpired=False):
    """대조군: 상태를 확인하지 않고 덮어쓴다 (읽고 쓰기 사이에 양보해 경쟁 구간을 넓힘)."""
    await asyncio.sleep(0.02)
    await db.execute(update(TransferDraft).where(TransferDraft.draft_id == draft_id).values(status=to_status))
    return True


async def amain(user, user_id):
    print(f"[1] 같은 초안({AMOUNT:,}원)을 10번 동시에 확인")
    r = await fire(user, new_draft(user_id))
    b, outs = moved()
    print(f"   {dict(r)} → B={b:,}, 출금 기록 {outs}건")
    good = check("1건 성공, 9건 DRAFT_NOT_PENDING, 한 번만 이체", (r["OK"], r["DRAFT_NOT_PENDING"], b, outs) == (1, 9, AMOUNT, 1))

    print("[대조군] 상태 조건 없이 다시")
    real = agent_repository.transition_pending
    agent_repository.transition_pending = naive_transition
    try:
        r = await fire(user, new_draft(user_id))
        b, outs = moved()
    finally:
        agent_repository.transition_pending = real
    print(f"   {dict(r)} → B={b:,}, 출금 기록 {outs}건 (정상은 1건)")
    control = outs > 1

    await engine.dispose()
    return good, control


def main():
    connect()
    user_id = make_user(LOGIN)
    ids["A"] = make_checking(user_id, NUMS["A"], per=1_000_000, daily=5_000_000)
    ids["B"] = make_checking(user_id, NUMS["B"], per=1_000_000, daily=5_000_000)
    try:
        good, control = run(amain(user_schema(user_id, LOGIN), user_id))
    finally:
        cleanup(LOGIN)
        print("정리 완료")
    passed = good and control
    finish(passed, f"검증 결과: {'통과' if passed else '실패'} (현재 코드 정상={good}, 대조군 이중 이체 재현={control})")


if __name__ == "__main__":
    main()
