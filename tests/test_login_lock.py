"""은행식 로그인 잠금 (C-090): 같은 아이디로 5회 연속 틀리면 잠금, 잠기면 맞는 비밀번호도 403, 해제는 본인 확인으로만.

실패는 비밀번호 검증 *전에* DB에서 원자적으로 먼저 센다(UPDATE ... RETURNING). 그래서 동시 요청·여러 IP에서도
정확히 5번만 검증된다. PostgreSQL에서의 같은 확인과 대조군: scripts/pg_login_lock_concurrency.py.
"""

from collections import Counter
import asyncio

import httpx
import pytest
from sqlalchemy import select

from avengers_bank import admin
from avengers_bank.core.database import SessionLocal, engine
from avengers_bank.core.security import DUMMY_HASH
from avengers_bank.domains.users import service as user_service_module
from avengers_bank.domains.users.models import RefreshToken, User
from avengers_bank.main import app

pytestmark = pytest.mark.anyio

LOGIN_ID = "lockuser"
PASSWORD = "Passw0rd!23"
WRONG = "Wrong0pass!"


async def signup(client):
    body = {"login_id": LOGIN_ID, "password": PASSWORD, "name": "토니", "phone": "010-1234-5678"}
    assert (await client.post("/users/signup", json=body)).status_code == 201


async def login(client, password=WRONG, login_id=LOGIN_ID):
    return await client.post("/users/login", json={"login_id": login_id, "password": password})


async def lock_state(device: bool = False) -> tuple[int, bool]:
    """(연속 실패 횟수, 잠김). device=False: 새 기기 채널, True: 등록 기기 채널(성공 로그인으로 기기를 등록한 뒤의 로그인·비밀번호 확인)."""
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.login_id == LOGIN_ID))
        if device:
            return user.device_failed_login_count, user.device_login_locked_at is not None
        return user.failed_login_count, user.login_locked_at is not None


def code(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


def from_ip(ip: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(ip, 1234)), base_url="http://test")


@pytest.fixture(autouse=True)
async def fresh_pool(client):
    """동시 요청 30개는 커넥션 풀(5+10)을 넘겨 대기열을 쓴다. 그 대기열이 이 테스트의 이벤트 루프에 묶이므로
    테스트가 끝나면 풀을 비운다(다음 테스트는 다른 루프에서 돈다)."""
    yield
    await engine.dispose()


@pytest.fixture
def verified(monkeypatch):
    """진짜 사용자 해시로 비밀번호를 검증한 횟수 (가짜 해시 검증은 세지 않는다)."""
    calls = []
    real = user_service_module.verify_password

    def spy(password, hashed):
        if hashed != DUMMY_HASH:
            calls.append(password)
        return real(password, hashed)

    monkeypatch.setattr(user_service_module, "verify_password", spy)
    return calls


async def test_five_consecutive_failures_lock_and_correct_password_is_refused(client):
    await signup(client)
    for n in range(1, 5):
        assert code(await login(client)) == (401, "INVALID_CREDENTIALS")
        assert await lock_state() == (n, False)  # 실패는 커밋돼 남는다 (401 예외로 롤백되지 않는다)
    fifth = await login(client)
    assert code(fifth) == (403, "ACCOUNT_LOCKED")
    assert "5회" in fifth.json()["error"]["message"] and "비밀번호 찾기" in fifth.json()["error"]["message"]
    assert await lock_state() == (5, True)
    assert code(await login(client, PASSWORD)) == (403, "ACCOUNT_LOCKED")  # 잠기면 맞는 비밀번호도 거절


async def test_success_resets_count_so_only_consecutive_failures_lock(client):
    await signup(client)
    for _ in range(4):
        await login(client)
    assert (await login(client, PASSWORD)).status_code == 200
    assert await lock_state() == (0, False)
    for _ in range(4):
        assert (await login(client)).status_code == 401  # 다시 4번까지는 잠기지 않는다
    assert await lock_state(device=True) == (4, False)  # 성공 로그인이 기기를 등록해 그 뒤는 등록 기기 채널
    assert await lock_state() == (0, False)


async def test_concurrent_wrong_logins_verify_exactly_five_then_lock(client, verified):
    await signup(client)
    responses = await asyncio.gather(*(login(client) for _ in range(30)))
    assert len(verified) == 5  # 30개가 동시에 와도 검증은 정확히 5번
    # 같은 IP라 21번째부터는 IP 한도(20회)가 DB에 닿기 전에 먼저 막는다
    codes = Counter(r.status_code for r in responses)
    # 4번 401, 5번째 실패는 403(잠금). 나머지는 잠기기 전에 온 것은 429(검증 중, '잠김'이 아님), 잠긴 뒤 온 것은 403.
    # 같은 IP라 IP 한도(20회)의 429도 섞인다
    assert codes[401] == 4 and codes[403] >= 1 and codes[401] + codes[403] + codes[429] == 30
    assert await lock_state() == (5, True)


async def test_failures_from_different_ips_share_one_count(client, verified):
    await signup(client)
    for n in range(4):
        async with from_ip(f"10.0.0.{n}") as c:
            assert (await login(c)).status_code == 401
    async with from_ip("10.0.0.9") as c:
        assert code(await login(c)) == (403, "ACCOUNT_LOCKED")  # IP를 바꿔도 같은 아이디면 5번째에 잠긴다
    clients = [from_ip(f"10.0.1.{n}") for n in range(10)]
    try:
        responses = await asyncio.gather(*(login(c, PASSWORD) for c in clients))
    finally:
        for c in clients:
            await c.aclose()
    assert {r.status_code for r in responses} == {403}
    assert len(verified) == 5


async def test_concurrent_wrong_logins_from_many_ips_verify_exactly_five(client, verified):
    await signup(client)
    clients = [from_ip(f"10.0.2.{n}") for n in range(30)]
    try:
        responses = await asyncio.gather(*(login(c) for c in clients))
    finally:
        for c in clients:
            await c.aclose()
    assert len(verified) == 5
    codes = Counter(r.status_code for r in responses)
    # 4번 401, 5번째 실패는 403(잠금). 나머지 25개는 잠기기 전에 왔으면 429(동시 요청이 검증 중), 잠긴 뒤면 403
    assert codes[401] == 4 and codes[403] >= 1 and codes[403] + codes[429] == 26


async def test_unknown_login_id_is_never_locked_only_ip_limited(client):
    responses = [await login(client, login_id="nobody") for _ in range(25)]
    assert [r.status_code for r in responses] == [401] * 20 + [429] * 5  # 403(잠금)은 없다: 행이 없으니 셀 곳도 없다


async def test_wrong_current_password_shares_the_login_counter(client):
    await signup(client)
    for _ in range(3):
        assert (await login(client)).status_code == 401
    tokens = (await login(client, PASSWORD)).json()["data"]  # 성공으로 0
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    bad = {"current_password": WRONG, "new_password": "N3w-Passw0rd!"}
    for _ in range(3):
        assert code(await client.patch("/users/me/password", json=bad, headers=headers)) == (400, "INVALID_CURRENT_PASSWORD")
    assert (await login(client)).status_code == 401  # 4번째 (로그인과 비밀번호 변경이 같은 카운터)
    assert code(await client.patch("/users/me/password", json=bad, headers=headers)) == (403, "ACCOUNT_LOCKED")
    assert await lock_state(device=True) == (5, True)
    good = {"current_password": PASSWORD, "new_password": "N3w-Passw0rd!"}
    assert code(await client.patch("/users/me/password", json=good, headers=headers)) == (403, "ACCOUNT_LOCKED")


async def test_concurrent_wrong_current_passwords_verify_exactly_five(client, verified):
    await signup(client)
    tokens = (await login(client, PASSWORD)).json()["data"]
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    verified.clear()
    bad = {"current_password": WRONG, "new_password": "N3w-Passw0rd!"}
    responses = await asyncio.gather(*(client.patch("/users/me/password", json=bad, headers=headers) for _ in range(10)))
    assert len(verified) == 5
    codes = Counter(r.status_code for r in responses)
    assert codes[400] == 4 and codes[403] >= 1 and codes[403] + codes[429] == 6  # 잠기기 전 동시 요청은 429
    assert await lock_state(device=True) == (5, True)


async def test_dev_unlock_endpoint(client):
    await signup(client)
    for _ in range(5):
        await login(client)
    assert (await client.post(f"/dev/users/{LOGIN_ID.upper()}/unlock")).status_code == 200
    assert await lock_state() == (0, False)
    assert (await login(client, PASSWORD)).status_code == 200
    assert code(await client.post("/dev/users/nobody/unlock")) == (404, "USER_NOT_FOUND")


async def test_admin_unlock_and_reset_password(client):
    await signup(client)
    session = (await login(client, PASSWORD)).json()["data"]
    for _ in range(5):
        await login(client)
    assert await admin.unlock(LOGIN_ID) is True
    assert await lock_state() == (0, False)
    assert await admin.unlock("nobody") is False

    for _ in range(5):
        await login(client)
    assert await admin.reset_password(LOGIN_ID, "Adm1n-Reset!") is True  # 잠금도 풀고, 모든 세션을 끊는다
    assert await lock_state() == (0, False)
    async with SessionLocal() as db:
        alive = await db.scalar(select(RefreshToken).where(RefreshToken.revoked_at.is_(None)))
    assert alive is None
    me = await client.get("/users/me", headers={"Authorization": f"Bearer {session['access_token']}"})
    assert me.status_code == 401
    assert (await login(client, PASSWORD)).status_code == 401
    assert (await login(client, "Adm1n-Reset!")).status_code == 200
    assert await admin.reset_password("nobody", "Adm1n-Reset!") is False


async def test_admin_new_password_rules():
    assert admin.check_new_password("tony", "Adm1n-Reset!") is None
    assert admin.check_new_password("tony", "short1!") == "비밀번호는 8자 이상 입력해 주세요."
    assert admin.check_new_password("tony", "password!!") == "비밀번호는 영문, 숫자, 특수문자를 모두 포함해야 합니다."
    assert admin.check_new_password("tony_1234", "TONY_1234") == "비밀번호는 아이디와 같을 수 없습니다."
