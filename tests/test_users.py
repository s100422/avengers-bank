from datetime import datetime, timedelta, timezone

import jwt
import pytest

from avengers_bank.core.config import get_settings
from avengers_bank.core.security import DUMMY_HASH, password_hash
from avengers_bank.domains.users import service as user_service_module

pytestmark = pytest.mark.anyio

SECRET = get_settings().jwt_secret_key.get_secret_value()

SIGNUP = {
    "login_id": "ironman",
    "password": "password1234",
    "name": "토니 스타크",
    "phone": "010-1234-5678",
}


async def test_root(client):
    response = await client.get("/")
    assert response.status_code == 200


async def test_signup_login_me(client):
    response = await client.post("/users/signup", json=SIGNUP)
    assert response.status_code == 201

    response = await client.post(
        "/users/login", json={"login_id": SIGNUP["login_id"], "password": SIGNUP["password"]}
    )
    assert response.status_code == 200
    token = response.json()["data"]["access_token"]

    response = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["data"]["login_id"] == SIGNUP["login_id"]


async def test_signup_duplicate_login_id(client):
    await client.post("/users/signup", json=SIGNUP)
    response = await client.post("/users/signup", json=SIGNUP)
    assert response.status_code == 409


async def test_signup_race_unique_violation_returns_409(client, monkeypatch):
    """동시 가입: 중복 조회는 둘 다 통과했지만 insert에서 unique 제약에 걸리는 상황."""
    from avengers_bank.domains.users.repository import user_repository

    await client.post("/users/signup", json=SIGNUP)

    async def not_found(db, login_id):
        return None

    monkeypatch.setattr(user_repository, "find_by_login_id", not_found)
    response = await client.post("/users/signup", json=SIGNUP)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LOGIN_ID_ALREADY_EXISTS"


async def test_update_me_changes_only_sent_fields(client, make_user):
    headers = await make_user("ironman")
    response = await client.patch("/users/me", json={"name": "페퍼", "phone": "010-9999-8888"}, headers=headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert (data["name"], data["phone"], data["login_id"]) == ("페퍼", "010-9999-8888", "ironman")

    again = await client.patch("/users/me", json={"nick_name": "아이언맨"}, headers=headers)
    assert (again.json()["data"]["nick_name"], again.json()["data"]["name"]) == ("아이언맨", "페퍼")  # 안 보낸 값은 그대로

    me = (await client.get("/users/me", headers=headers)).json()["data"]  # 실제로 저장됐는지
    assert (me["name"], me["phone"], me["nick_name"]) == ("페퍼", "010-9999-8888", "아이언맨")


async def test_update_me_can_clear_nickname_and_empty_body_is_noop(client, make_user):
    headers = await make_user("ironman")
    await client.patch("/users/me", json={"nick_name": "토니"}, headers=headers)

    cleared = await client.patch("/users/me", json={"nick_name": None}, headers=headers)
    assert cleared.json()["data"]["nick_name"] is None

    noop = await client.patch("/users/me", json={}, headers=headers)
    assert noop.status_code == 200 and noop.json()["data"]["name"] == "토니"


@pytest.mark.parametrize(
    "body",
    [
        {"name": None}, {"phone": None},  # 가입 때 필수였던 값은 비울 수 없다
        {"name": ""}, {"phone": "123"}, {"name": "x" * 51}, {"nick_name": "x" * 51},
        {"login_id": "hacker"}, {"password": "newpassword1"}, {"user_id": 99},  # 바꿀 수 없는 필드
    ],
    ids=["null_name", "null_phone", "empty_name", "short_phone", "long_name", "long_nick",
         "login_id", "password", "user_id"],
)
async def test_update_me_rejects_invalid_requests(client, make_user, body):
    headers = await make_user("ironman")
    response = await client.patch("/users/me", json=body, headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    me = (await client.get("/users/me", headers=headers)).json()["data"]
    assert (me["name"], me["login_id"]) == ("토니", "ironman")  # 거절된 요청은 아무것도 바꾸지 않는다


async def test_update_me_only_changes_own_account(client, make_user):
    tony, bruce = await make_user("ironman"), await make_user("hulk")
    await client.patch("/users/me", json={"name": "브루스 배너"}, headers=bruce)
    assert (await client.get("/users/me", headers=tony)).json()["data"]["name"] == "토니"


async def test_update_me_requires_login(client):
    assert (await client.patch("/users/me", json={"name": "x"})).status_code == 401


# ── 로그인 실패: 없는 아이디와 틀린 비밀번호를 구분할 수 없어야 한다 (C-026) ──


async def test_login_failure_looks_the_same_for_wrong_password_and_unknown_id(client):
    await client.post("/users/signup", json=SIGNUP)
    wrong = await client.post("/users/login", json={"login_id": SIGNUP["login_id"], "password": "wrong-password"})
    unknown = await client.post("/users/login", json={"login_id": "nobody-here", "password": "wrong-password"})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()  # 응답 내용으로도 아이디가 있는지 알 수 없다
    assert wrong.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert wrong.headers["www-authenticate"] == unknown.headers["www-authenticate"] == "Bearer"


async def test_login_checks_password_even_for_unknown_login_id(client, monkeypatch):
    """없는 아이디도 비밀번호 검증(가짜 해시)을 거친다. 건너뛰면 응답 시간으로 가입된 아이디를 알 수 있다."""
    checked = []
    real = user_service_module.verify_password

    def spy(password, hashed_password):
        checked.append(hashed_password)
        return real(password, hashed_password)

    monkeypatch.setattr(user_service_module, "verify_password", spy)
    response = await client.post("/users/login", json={"login_id": "nobody-here", "password": "whatever1234"})
    assert response.status_code == 401
    assert checked == [DUMMY_HASH]


def test_dummy_hash_is_a_real_hash():
    """진짜 해시가 아니면 검증이 일찍 끝나서(시간이 짧아져서) 가짜 해시의 의미가 없다."""
    assert DUMMY_HASH.startswith("$argon2")
    assert password_hash.verify("any-password", DUMMY_HASH) is False  # 형식이 틀리면 여기서 예외가 난다


# ── 입력 검증(422) ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "override",
    [
        {"login_id": "abc"}, {"login_id": "x" * 51},
        {"password": "short1!"}, {"password": "x" * 129},
        {"name": ""}, {"name": "x" * 51},
        {"phone": "12345678"}, {"phone": "1" * 21},
        {"nick_name": "x" * 51},
    ],
    ids=["login_id_3", "login_id_51", "password_7", "password_129", "name_empty", "name_51",
         "phone_8", "phone_21", "nick_51"],
)
async def test_signup_validation_errors(client, override):
    response = await client.post("/users/signup", json={**SIGNUP, **override})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR" and error["details"]  # 어느 필드가 문제인지 알려 준다
    login = await client.post("/users/login", json={"login_id": SIGNUP["login_id"], "password": SIGNUP["password"]})
    assert login.status_code == 401  # 거절된 가입은 계정을 만들지 않는다


@pytest.mark.parametrize("missing", ["login_id", "password", "name", "phone"])
async def test_signup_requires_fields(client, missing):
    body = {k: v for k, v in SIGNUP.items() if k != missing}
    assert (await client.post("/users/signup", json=body)).status_code == 422


async def test_signup_accepts_boundary_lengths(client):
    body = {"login_id": "abcd", "password": "12345678", "name": "x", "phone": "123456789", "nick_name": "n" * 50}
    assert (await client.post("/users/signup", json=body)).status_code == 201


@pytest.mark.parametrize(
    "body",
    [{"login_id": "", "password": "x"}, {"login_id": "x", "password": ""}, {"password": "x"}, {"login_id": "x"},
     {"login_id": "x" * 51, "password": "x"}, {"login_id": "x", "password": "x" * 129}],
    ids=["empty_id", "empty_password", "no_id", "no_password", "id_51", "password_129"],
)
async def test_login_validation_errors(client, body):
    response = await client.post("/users/login", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# ── 인증(401): 토큰이 없거나 잘못됐을 때 ─────────────────────────────


def token(sub="1", key=SECRET, algorithm="HS256", expires_in=timedelta(minutes=5), with_exp=True):
    now = datetime.now(timezone.utc)
    payload = {"sub": sub, "iat": now}
    if with_exp:
        payload["exp"] = now + expires_in
    return jwt.encode(payload, key, algorithm=algorithm)


async def test_helper_makes_a_valid_token(client):
    """아래 거절 테스트가 '토큰을 잘못 만들어서' 통과하는 착시가 아님을 확인하는 대조군."""
    signup = await client.post("/users/signup", json=SIGNUP)
    user_id = signup.json()["data"]["user_id"]
    response = await client.get("/users/me", headers={"Authorization": f"Bearer {token(sub=str(user_id))}"})
    assert response.status_code == 200 and response.json()["data"]["login_id"] == SIGNUP["login_id"]


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer"}],
                         ids=["no_header", "not_bearer", "no_token"])
async def test_me_without_credentials(client, headers):
    response = await client.get("/users/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "bad_token",
    [
        "not-a-token",
        token(expires_in=timedelta(minutes=-1)),
        token(key="another-secret-key-another-secret-key-00"),
        token(with_exp=False),
        token(key=None, algorithm="none"),
        token(sub="abc"),
        token(sub="999"),
    ],
    ids=["garbage", "expired", "wrong_key", "no_exp", "alg_none", "sub_not_number", "user_not_found"],
)
async def test_me_rejects_bad_tokens(client, bad_token):
    await client.post("/users/signup", json=SIGNUP)  # 사용자는 있다 (1번). 토큰이 문제다
    response = await client.get("/users/me", headers={"Authorization": f"Bearer {bad_token}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


# ── 응답에 비밀번호가 새지 않는다 ─────────────────────────────────────


async def test_responses_never_expose_password(client):
    signup = await client.post("/users/signup", json=SIGNUP)
    login = await client.post("/users/login", json={"login_id": SIGNUP["login_id"], "password": SIGNUP["password"]})
    access_token = login.json()["data"]["access_token"]
    me = await client.get("/users/me", headers={"Authorization": f"Bearer {access_token}"})
    patched = await client.patch("/users/me", json={"name": "페퍼"}, headers={"Authorization": f"Bearer {access_token}"})

    for response in (signup, me, patched):
        assert not {"password", "hashed_password"} & set(response.json()["data"])
        assert SIGNUP["password"] not in response.text
    assert "$argon2" not in signup.text + login.text + me.text + patched.text
