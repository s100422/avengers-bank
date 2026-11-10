import os
import re

# 앱을 import하기 전에 테스트용 설정을 넣는다 (SQLite 파일 DB).
# TEST_DATABASE_URL로 다른 SQLite 파일을 쓰면 테스트를 동시에 두 벌 돌려도 서로 지우지 않는다
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ["JWT_SECRET_KEY"] = "test-secret-key-test-secret-key-0000"
os.environ["ENABLE_DEV_ENDPOINTS"] = "true"  # /dev/... 충전 API 테스트용
# 테스트 클라이언트는 http://test로 부르고 경로에 /api 프록시가 없다: Secure 쿠키는 http로 안 가고 Path도 안 맞는다
os.environ["COOKIE_SECURE"] = "false"
os.environ["REFRESH_COOKIE_PATH"] = "/users"
# ClearingHub 연동 시험용 키: docs/SPEC.md 2.3의 공개된 검증 전용 값 (운영 키 아님)
BANK_KEY, BANK_PUB = "D7frsUqSl9ZuC+7EpHfY1+w6+dAlWqg8vuHVtZfdpg4=", "gxCDPKbN/rIXKDJgn4GZh5JY7I65Cwbk3A/mJjTtPzY="
HUB_KEY, HUB_PUB = "cycR/h4ydSTPkBGuRFO340cDtdAdwrXQjKC4N1GPgtQ=", "yZdBWoR7swp/3CQvh4c58oahhbjxVeaxWWtqmqwDXdo="
os.environ.update(BANK_CODE="903", BANK_API_KEY="chk_test", BANK_PRIVATE_KEY=BANK_KEY, HUB_PUBLIC_KEY=HUB_PUB)

import pytest
from httpx import ASGITransport, AsyncClient

import avengers_bank.domains.accounts.models  # noqa: F401  모든 테이블을 Base에 등록
import avengers_bank.domains.agent.models  # noqa: F401
import avengers_bank.domains.cards.models  # noqa: F401
import avengers_bank.domains.products.models  # noqa: F401
import avengers_bank.domains.interbank.models  # noqa: F401
import avengers_bank.domains.money_management.models  # noqa: F401
import avengers_bank.domains.transfers.models  # noqa: F401
import avengers_bank.domains.terms.models  # noqa: F401
from avengers_bank.core.database import Base, engine
from avengers_bank.core.login_limiter import login_limiter, verification_ip_limiter
from avengers_bank.domains.verification.sms import dev_inbox
from avengers_bank.main import app
from tests.terms_helpers import OPEN_PATHS, agree_all
from tests.verification_helpers import auto_device_login, auto_signup_token


ORIGIN = "http://localhost:5173"  # 기본 CORS_ORIGINS에 들어 있는 값


@pytest.fixture
def anyio_backend():
    return "asyncio"


class BankClient(AsyncClient):
    """기존 가입 테스트용: terms 없이 보낸 가입 요청에 '현재 약관 모두 동의'를 붙인다 (C-075).

    약관 검증 자체를 보는 테스트(test_terms_consent.py)는 auto_terms = False로 끄고 직접 보낸다.
    """

    auto_terms = True
    # 계좌 비밀번호: 계좌 개설과 돈이 나가는 요청에 없으면 DEFAULT_ACCOUNT_PASSWORD를 붙인다.
    # 계좌 비밀번호 자체를 보는 테스트(test_account_password.py)는 auto_account_password = False로 끄고 직접 보낸다
    auto_account_password = True
    # 휴대폰 인증(C-090): 가입 요청에 phone_verification_token이 없으면 발송 → 개발용 문자함 → 확인을 거쳐 붙인다.
    # 이 자동 인증은 발송 제한을 쓰지 않는다. 인증 자체를 보는 테스트(test_verification.py)는 False로 끄고 직접 보낸다
    auto_phone_verification = True
    # 새 기기 인증: 로그인이 DEVICE_VERIFICATION_REQUIRED를 돌려주면 개발용 문자함으로 인증을 끝내(실제 API 경로 그대로)
    # 최종 로그인 응답을 돌려준다. 그 브라우저(쿠키 보관함)는 이후 등록 기기다. 기기 로그인 자체를 보는 테스트는 False로 끈다
    auto_device_verification = True

    async def post(self, url, *args, json=None, **kwargs):
        if (
            self.auto_phone_verification and str(url) == "/users/signup"
            and isinstance(json, dict) and "phone_verification_token" not in json
        ):
            json = {**json, **await auto_signup_token(self, json.get("phone"))}
        kind = OPEN_PATHS.get(str(url))
        if kind and self.auto_terms and isinstance(json, dict) and "terms" not in json and "product_id" in json:
            json = {**json, "terms": await agree_all(self, kind, json["product_id"])}
        response = await super().post(url, *args, json=json, **kwargs)
        if self.auto_device_verification and str(url) == "/users/login" and response.status_code == 200:
            data = response.json()["data"]
            if data.get("status") == "DEVICE_VERIFICATION_REQUIRED":
                return await auto_device_login(self, data["challenge_token"])
        return response

    async def request(self, method, url, *args, json=None, **kwargs):
        # post()도 여기를 지난다. client.request("POST", ...)로 보낸 요청에도 붙이려고 post가 아니라 여기서 한다
        if self.auto_account_password and method.upper() == "POST":
            json = with_account_password(str(url), json)
        return await super().request(method, url, *args, json=json, **kwargs)


DEFAULT_ACCOUNT_PASSWORD = "1357"
# 본문에 account_password가 필요한 경로: 계좌 개설 3종 + 돈이 나가는 6곳 (예금 개설은 출금 계좌 비밀번호도)
_ACCOUNT_PASSWORD_PATHS = re.compile(
    r"^/accounts/(checking|deposit|savings)$|^/transfers(/savings)?$|^/accounts/(checking|deposit|savings)/\d+/close$"
    r"|^/cards/credit/\d+/bills/\d+/payments$|^/agent/transfers/[^/]+/confirm$"
)


def with_account_password(path: str, json):
    if not _ACCOUNT_PASSWORD_PATHS.match(path) or not (json is None or isinstance(json, dict)):
        return json
    json = {"account_password": DEFAULT_ACCOUNT_PASSWORD, **(json or {})}
    if path == "/accounts/deposit":
        json = {"from_account_password": DEFAULT_ACCOUNT_PASSWORD, **json}
    return json


@pytest.fixture
async def client():
    login_limiter.clear()  # 테스트끼리 실패 횟수가 섞이지 않게 한다
    verification_ip_limiter.clear()
    dev_inbox.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    # Origin: 쿠키로 인증하는 요청(갱신·로그아웃·기기 해제)은 허용된 Origin이 있어야 한다. 브라우저가 보내는 값을 흉내 낸다
    async with BankClient(
        transport=ASGITransport(app=app), base_url="http://test", headers={"Origin": ORIGIN}
    ) as ac:
        yield ac


@pytest.fixture
def make_user(client):
    """회원가입 + 로그인을 하고 Authorization 헤더를 돌려주는 함수."""

    async def _make(login_id: str = "ironman") -> dict[str, str]:
        body = {"login_id": login_id, "password": "Passw0rd!23", "name": "토니", "phone": "010-1234-5678"}
        await client.post("/users/signup", json=body)
        response = await client.post(
            "/users/login", json={"login_id": login_id, "password": "Passw0rd!23"}
        )
        return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}

    return _make


@pytest.fixture
async def account_products(client):
    """계좌 상품 3종 (CHECKING=1, DEPOSIT=2, SAVINGS=3)."""
    from avengers_bank.core.database import SessionLocal
    from avengers_bank.domains.products.models import AccountProduct

    async with SessionLocal() as db, db.begin():
        db.add_all([
            AccountProduct(type=t, name=t, description="d", interest_rate=1)
            for t in ("CHECKING", "DEPOSIT", "SAVINGS")
        ])
