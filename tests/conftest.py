import os

# 앱을 import하기 전에 테스트용 설정을 넣는다 (SQLite 파일 DB).
# TEST_DATABASE_URL로 다른 SQLite 파일을 쓰면 테스트를 동시에 두 벌 돌려도 서로 지우지 않는다
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ["JWT_SECRET_KEY"] = "test-secret-key-test-secret-key-0000"
os.environ["ENABLE_DEV_ENDPOINTS"] = "true"  # /dev/... 충전 API 테스트용

import pytest
from httpx import ASGITransport, AsyncClient

import avengers_bank.domains.accounts.models  # noqa: F401  모든 테이블을 Base에 등록
import avengers_bank.domains.agent.models  # noqa: F401
import avengers_bank.domains.cards.models  # noqa: F401
import avengers_bank.domains.products.models  # noqa: F401
import avengers_bank.domains.terms.models  # noqa: F401
from avengers_bank.core.database import Base, engine
from avengers_bank.core.login_limiter import login_limiter
from avengers_bank.main import app
from tests.terms_helpers import OPEN_PATHS, agree_all


@pytest.fixture
def anyio_backend():
    return "asyncio"


class BankClient(AsyncClient):
    """기존 가입 테스트용: terms 없이 보낸 가입 요청에 '현재 약관 모두 동의'를 붙인다 (C-075).

    약관 검증 자체를 보는 테스트(test_terms_consent.py)는 auto_terms = False로 끄고 직접 보낸다.
    """

    auto_terms = True

    async def post(self, url, *args, json=None, **kwargs):
        kind = OPEN_PATHS.get(str(url))
        if kind and self.auto_terms and isinstance(json, dict) and "terms" not in json and "product_id" in json:
            json = {**json, "terms": await agree_all(self, kind, json["product_id"])}
        return await super().post(url, *args, json=json, **kwargs)


@pytest.fixture
async def client():
    login_limiter.clear()  # 테스트끼리 실패 횟수가 섞이지 않게 한다
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with BankClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def make_user(client):
    """회원가입 + 로그인을 하고 Authorization 헤더를 돌려주는 함수."""

    async def _make(login_id: str = "ironman") -> dict[str, str]:
        body = {"login_id": login_id, "password": "password1234", "name": "토니", "phone": "010-1234-5678"}
        await client.post("/users/signup", json=body)
        response = await client.post(
            "/users/login", json={"login_id": login_id, "password": "password1234"}
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
