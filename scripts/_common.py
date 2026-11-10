"""scripts/의 PostgreSQL 검증 스크립트가 같이 쓰는 도구.

개발용 DB(docker compose, 127.0.0.1)에서만 돌린다. 스크립트는 `verify_...` 이름의 사용자와 그 계좌·카드를
만들고, 끝나면(실패해도) 지운다. 시작할 때도 같은 이름의 찌꺼기를 먼저 지운다.
"""

import asyncio
import selectors
import sys
from datetime import datetime, timezone
from sqlalchemy.engine import make_url

from sqlalchemy import create_engine, text

import avengers_bank.main  # noqa: F401  앱과 같이 모든 모델·라우터를 불러온다 (FK 대상 테이블 해석에 필요)
from avengers_bank.core.config import get_settings
from avengers_bank.domains.users.schemas import UserResponse

_engine = None


def connect(allowed_host: str | None = None):
    """개발용 PostgreSQL에만 연결한다. 시드 상품이 없으면 안내하고 끝낸다.

    allowed_host: 운영 시연 계정 시드처럼 로컬이 아닌 DB에 일부러 쓸 때, 실행하는 사람이 DB 호스트를 정확히 적는다.
    """
    global _engine
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")  # sys.exit(메시지)는 표준 오류로 나간다
    url = get_settings().database_url
    host = make_url(url).host  # urlsplit은 비밀번호에 /·?·# 가 있으면 사용자 이름을 호스트로 잘못 읽는다
    if not url.startswith("postgresql") or host not in ("127.0.0.1", "localhost", "::1", *(h for h in [allowed_host] if h)):
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


ACCOUNT_PASSWORD = "1357"  # SQL로 만든 계좌의 계좌 비밀번호. 돈이 나가는 서비스 호출에 이 값을 넘긴다
_account_password_hash: str | None = None


def account_password_hash() -> str:
    """ACCOUNT_PASSWORD의 argon2 해시 (한 번만 만든다). SQL로 계좌를 넣을 때 password_hash 컬럼에 쓴다."""
    global _account_password_hash
    if _account_password_hash is None:
        from avengers_bank.core.security import hash_password

        _account_password_hash = hash_password(ACCOUNT_PASSWORD)
    return _account_password_hash


def make_checking(user_id: int, account_num: str, balance: int = 0, per: int = 1, daily: int = 1) -> int:
    return one(
        "insert into checking_accounts(user_id, product_id, account_num, balance, per_transfer_limit, daily_transfer_limit,"
        " password_hash) values (:u, :p, :n, :b, :per, :daily, :h) returning checking_account_id",
        u=user_id, p=product_id("account_products", "CHECKING"), n=account_num, b=balance, per=per, daily=daily,
        h=account_password_hash(),
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
        f"delete from terms_consents where user_id in {u}",
        f"delete from refresh_tokens where user_id in {u}",
        f"delete from user_devices where user_id in {u}",
        # 가입 인증은 user_id가 비어 있으므로 번호로도 지운다(남기면 번호당 15분 3번 발송 제한에 걸린다)
        f"delete from verification_codes where user_id in {u} or phone in (select phone from users where login_id = :l)",
        f"delete from agent_transfer_drafts where user_id in {u}",
        f"delete from agent_messages where conversation_id in (select conversation_id from agent_conversations where user_id in {u})",
        f"delete from agent_conversations where user_id in {u}",
        f"delete from credit_card_histories where credit_card_id in {credit}",
        f"delete from debit_card_histories where debit_card_id in {debit}",
        f"delete from credit_card_bills where credit_card_id in {credit}",
        f"delete from credit_cards where user_id in {u}",
        f"delete from debit_cards where user_id in {u}",
        f"delete from account_notifications where user_id in {u}",
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


async def signup_via_api(client, body: dict) -> None:
    """실제 API로 가입한다: 휴대폰 인증번호 발송 → 개발용 문자함(같은 프로세스의 메모리)에서 코드 읽기 → 확인 → 가입."""
    import re

    from avengers_bank.domains.verification.sms import dev_messages
    from avengers_bank.domains.users.validators import format_phone

    sent = await client.post("/verification/phone/send", json={"phone": body["phone"], "purpose": "SIGNUP_PHONE"})
    assert sent.status_code == 200, sent.text
    code = re.search(r"\d{6}", dev_messages(format_phone(body["phone"]))[0][0]).group()
    verified = await client.post(
        "/verification/phone/verify", json={"verification_id": sent.json()["data"]["verification_id"], "code": code}
    )
    assert verified.status_code == 200, verified.text
    token = verified.json()["data"]["verification_token"]
    response = await client.post("/users/signup", json={**body, "phone_verification_token": token})
    assert response.status_code == 201, response.text


def origin_header() -> dict[str, str]:
    """쿠키로 인증하는 요청(갱신·로그아웃·기기 해제)이 요구하는 Origin. 브라우저가 보내는 값을 흉내 낸다."""
    return {"Origin": get_settings().cors_origin_list[0]}


def cookie_value(response, name: str = "refresh_token") -> str | None:
    """응답의 Set-Cookie에서 쿠키 원문을 꺼낸다. httpx 보관함에 맡기지 않는 이유: 설정(COOKIE_SECURE=true, Path=/api/users)
    때문에 http://test/users/...로 가는 요청에는 보관함이 쿠키를 싣지 않는다 — 스크립트가 Cookie 헤더를 직접 만든다."""
    from http.cookies import SimpleCookie

    jar = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        jar.load(header)
    return jar[name].value if name in jar else None


def cookie_headers(refresh_token: str | None = None, device_token: str | None = None) -> dict[str, str]:
    """갱신 토큰·기기 토큰 쿠키 + Origin 헤더."""
    parts = [f"{n}={v}" for n, v in (("refresh_token", refresh_token), ("device_token", device_token)) if v is not None]
    return {**origin_header(), "Cookie": "; ".join(parts)}


def register_device_sql(login_id: str) -> str:
    """등록 기기를 SQL로 직접 만들고 기기 쿠키 원문을 돌려준다(스크립트 준비용).

    실제 흐름(휴대폰 인증 → POST /users/login/device)은 번호당 15분 3번 발송 한도가 있어 기기를 여러 개 만들 수 없다.
    기기 쿠키를 가진 요청은 휴대폰 인증 없이 '등록 기기' 채널로 로그인한다.
    """
    from avengers_bank.core.security import hash_refresh_token, new_refresh_token

    raw = new_refresh_token()
    one(
        "insert into user_devices(user_id, token_hash, label) values ((select user_id from users where login_id = :l), :h, 'script')"
        " returning device_id", l=login_id, h=hash_refresh_token(raw),
    )
    return raw


async def login_via_api(client, login_id: str, password: str, device_token: str | None = None):
    """POST /users/login. device_token(register_device_sql)이 있으면 등록 기기로 바로 로그인한다.
    없고 새 기기 챌린지가 오면 실제 API로 휴대폰 인증을 끝낸다(개발용 문자함 = 같은 프로세스 메모리). 최종 응답을 돌려준다."""
    import re

    from avengers_bank.domains.verification.sms import dev_messages

    headers = {"Cookie": f"device_token={device_token}"} if device_token else None
    response = await client.post("/users/login", json={"login_id": login_id, "password": password}, headers=headers)
    data = response.json().get("data") or {}
    if data.get("status") != "DEVICE_VERIFICATION_REQUIRED":
        return response
    challenge = data["challenge_token"]
    phone = one("select phone from users where login_id = :l", l=login_id)
    sent = await client.post("/users/login/device/send", json={"challenge_token": challenge})
    assert sent.status_code == 200, sent.text
    code = re.search(r"\d{6}", dev_messages(phone)[0][0]).group()
    verified = await client.post(
        "/verification/phone/verify", json={"verification_id": sent.json()["data"]["verification_id"], "code": code}
    )
    assert verified.status_code == 200, verified.text
    return await client.post("/users/login/device", json={
        "challenge_token": challenge, "phone_verification_token": verified.json()["data"]["verification_token"],
    })


def run(coro):
    """Windows에서 psycopg 비동기 모드는 Selector 이벤트 루프가 필요하다 (C-016)."""
    return asyncio.run(coro, loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))


def check(label: str, condition: bool) -> bool:
    print(f"   {'✔' if condition else '✘'} {label}")
    return condition


def finish(passed: bool, summary: str) -> None:
    print("\n" + summary)
    sys.exit(0 if passed else 1)
