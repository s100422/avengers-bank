"""scripts/의 PostgreSQL 검증 스크립트가 같이 쓰는 도구.

개발용 DB(docker compose, 127.0.0.1)에서만 돌린다. 스크립트는 `verify_...` 이름의 사용자와 그 계좌·카드를
만들고, 끝나면(실패해도) 지운다. 시작할 때도 같은 이름의 찌꺼기를 먼저 지운다.
"""

import asyncio
import selectors
import sys
from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy import create_engine, text

import avengers_bank.main  # noqa: F401  앱과 같이 모든 모델·라우터를 불러온다 (FK 대상 테이블 해석에 필요)
from avengers_bank.core.config import get_settings
from avengers_bank.domains.users.schemas import UserResponse

_engine = None


def connect():
    """개발용 PostgreSQL에만 연결한다. 시드 상품이 없으면 안내하고 끝낸다."""
    global _engine
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")  # sys.exit(메시지)는 표준 오류로 나간다
    url = get_settings().database_url
    host = urlsplit(url).hostname
    if not url.startswith("postgresql") or host not in ("127.0.0.1", "localhost", "::1"):
        sys.exit(f"개발용 PostgreSQL(127.0.0.1)에서만 실행한다. 지금 DATABASE_URL의 호스트: {host}")
    _engine = create_engine(url)
    for table in ("account_products", "card_products"):
        if not one(f"select count(*) from {table}"):
            sys.exit("상품 데이터가 없다. 먼저 실행: uv run python -m avengers_bank.seed")


def one(stmt: str, **params):
    """SQL 한 문장을 실행하고 첫 값을 돌려준다 (insert ... returning 포함)."""
    with _engine.begin() as conn:
        return conn.execute(text(stmt), params).scalar()


def execute(stmt: str, **params) -> None:
    with _engine.begin() as conn:
        conn.execute(text(stmt), params)


def product_id(table: str, type_: str) -> int:
    return one(f"select product_id from {table} where type = :t order by 1 limit 1", t=type_)


def make_user(login_id: str) -> int:
    cleanup(login_id)  # 이전 실행이 중간에 끊겨서 남긴 찌꺼기 제거
    return one(
        "insert into users(login_id, hashed_password, name, phone) values (:l, 'x', 't', '010') returning user_id",
        l=login_id,
    )


def make_checking(user_id: int, account_num: str, balance: int = 0, per: int = 1, daily: int = 1) -> int:
    return one(
        "insert into checking_accounts(user_id, product_id, account_num, balance, per_transfer_limit, daily_transfer_limit)"
        " values (:u, :p, :n, :b, :per, :daily) returning checking_account_id",
        u=user_id, p=product_id("account_products", "CHECKING"), n=account_num, b=balance, per=per, daily=daily,
    )


def user_schema(user_id: int, login_id: str) -> UserResponse:
    """서비스 함수에 넘기는 '로그인한 사용자'."""
    return UserResponse(
        user_id=user_id, login_id=login_id, name="t", nick_name=None, phone="010",
        created_at=datetime.now(timezone.utc),
    )


def cleanup(login_id: str) -> None:
    """이 사용자의 모든 데이터를 FK 순서대로 지운다."""
    u = "(select user_id from users where login_id = :l)"
    credit = f"(select credit_card_id from credit_cards where user_id in {u})"
    debit = f"(select debit_card_id from debit_cards where user_id in {u})"
    statements = [
        f"delete from credit_card_histories where credit_card_id in {credit}",
        f"delete from debit_card_histories where debit_card_id in {debit}",
        f"delete from credit_card_bills where credit_card_id in {credit}",
        f"delete from credit_cards where user_id in {u}",
        f"delete from debit_cards where user_id in {u}",
        f"delete from checking_account_histories where checking_account_id in (select checking_account_id from checking_accounts where user_id in {u})",
        f"delete from deposit_account_histories where deposit_account_id in (select deposit_account_id from deposit_accounts where user_id in {u})",
        f"delete from savings_account_histories where savings_account_id in (select savings_account_id from savings_accounts where user_id in {u})",
        f"delete from checking_accounts where user_id in {u}",
        f"delete from deposit_accounts where user_id in {u}",
        f"delete from savings_accounts where user_id in {u}",
        "delete from users where login_id = :l",
    ]
    with _engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement), {"l": login_id})


def run(coro):
    """Windows에서 psycopg 비동기 모드는 Selector 이벤트 루프가 필요하다 (C-016)."""
    return asyncio.run(coro, loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))


def check(label: str, condition: bool) -> bool:
    print(f"   {'✔' if condition else '✘'} {label}")
    return condition


def finish(passed: bool, summary: str) -> None:
    print("\n" + summary)
    sys.exit(0 if passed else 1)
