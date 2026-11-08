"""IP 한도(메모리)를 동시 요청으로 우회할 수 없는지 (시도를 검증 전에 먼저 센다).

같은 아이디를 계속 틀리는 경우(예전 아이디+IP 5회 C-082, 아이디별 느리게 C-089)는 DB 잠금으로 바뀌었다
→ tests/test_login_lock.py (C-090).
"""

import asyncio

import pytest

pytestmark = pytest.mark.anyio

LOGIN_ID = "limituser"
PASSWORD = "Passw0rd!23"


async def signup_and_login(client) -> dict[str, str]:
    body = {"login_id": LOGIN_ID, "password": PASSWORD, "name": "토니", "phone": "010-1234-5678"}
    assert (await client.post("/users/signup", json=body)).status_code == 201
    response = await client.post("/users/login", json={"login_id": LOGIN_ID, "password": PASSWORD})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def statuses(responses) -> list[int]:
    return sorted(r.status_code for r in responses)


async def login(client, login_id=LOGIN_ID, password="Wrong0pass!"):
    return await client.post("/users/login", json={"login_id": login_id, "password": password})


async def test_ip_limit_applies_to_concurrent_requests_with_different_ids(client):
    responses = await asyncio.gather(*(login(client, f"nobody{i:02d}") for i in range(30)))
    assert statuses(responses) == [401] * 20 + [429] * 10
    assert all("Retry-After" in r.headers for r in responses if r.status_code == 429)


async def test_ip_limit_counts_failures_on_real_ids_too(client):
    """있는 아이디를 틀린 것도 IP 한도에 들어간다: 아이디 하나당 4번씩(잠기기 직전) 여러 아이디를 찌르는 경우."""
    await signup_and_login(client)
    for _ in range(4):
        assert (await login(client)).status_code == 401
    for i in range(16):
        assert (await login(client, f"nobody{i:02d}")).status_code == 401
    assert (await login(client, "nobody99")).status_code == 429


async def test_success_does_not_count_toward_ip_and_keeps_other_failures(client):
    await signup_and_login(client)
    for i in range(19):
        assert (await login(client, f"nobody{i:02d}")).status_code == 401
    assert (await login(client, password=PASSWORD)).status_code == 200  # 성공은 IP 한도에서 빠진다
    assert (await login(client, "nobody98")).status_code == 401  # 20번째 실패
    assert (await login(client, "nobody99")).status_code == 429  # 성공이 다른 실패 기록을 지워 주지는 않는다


async def test_successful_logins_do_not_fill_ip_limit(client):
    await signup_and_login(client)
    for _ in range(25):
        assert (await login(client, password=PASSWORD)).status_code == 200


async def test_password_change_rule_errors_do_not_count_as_failures(client):
    headers = await signup_and_login(client)
    same = {"current_password": PASSWORD, "new_password": PASSWORD}
    for _ in range(6):
        response = await client.patch("/users/me/password", json=same, headers=headers)
        assert response.json()["error"]["code"] == "SAME_PASSWORD"
    ok = {"current_password": PASSWORD, "new_password": "N3w-Passw0rd!"}
    assert (await client.patch("/users/me/password", json=ok, headers=headers)).status_code == 200
