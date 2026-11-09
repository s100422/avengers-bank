from datetime import datetime, timedelta, timezone

import jwt
import pytest

from avengers_bank.core.config import get_settings
from avengers_bank.core.security import DUMMY_HASH, password_hash
from avengers_bank.domains.users import service as user_service_module
from tests.verification_helpers import phone_token

pytestmark = pytest.mark.anyio

SECRET = get_settings().jwt_secret_key.get_secret_value()

SIGNUP = {
    "login_id": "ironman",
    "password": "Passw0rd!23",
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
    token = await phone_token(client, "010-9999-8888", "CHANGE_PHONE", headers)  # 번호를 바꾸려면 새 번호로 인증
    response = await client.patch(
        "/users/me", json={"name": "페퍼", "phone": "010-9999-8888", "phone_verification_token": token}, headers=headers
    )
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
        {"name": ""}, {"name": "   "}, {"phone": "123"}, {"phone": "02-123-4567"}, {"phone": "010-1234-567a"},
        {"name": "x" * 51}, {"nick_name": "x" * 51},
        {"login_id": "hacker"}, {"password": "newpassword1"}, {"user_id": 99},  # 바꿀 수 없는 필드
    ],
    ids=["null_name", "null_phone", "empty_name", "blank_name", "short_phone", "landline", "phone_letter",
         "long_name", "long_nick",
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
        {"login_id": "iron-man"}, {"login_id": "아이언맨"}, {"login_id": "x" * 21}, {"login_id": "iron man"},
        {"password": "Short1!"}, {"password": "Aa1!" * 33},
        {"password": "password!!"}, {"password": "12345678!"}, {"password": "Password12"}, {"password": "        "},
        {"name": "   "}, {"phone": "010-1234-56"}, {"phone": "02-1234-5678"},
        {"name": ""}, {"name": "x" * 51},
        {"phone": "12345678"}, {"phone": "1" * 21},
        {"nick_name": "x" * 51},
    ],
    ids=["login_id_3", "login_id_51", "login_id_hyphen", "login_id_hangul", "login_id_21", "login_id_space",
         "password_7", "password_132", "password_no_digit", "password_no_letter", "password_no_special",
         "password_blank", "name_blank", "phone_short", "phone_landline", "name_empty", "name_51",
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
    body = {"login_id": "abcd", "password": "Abcdef1!", "name": "x", "phone": "0111234567", "nick_name": "n" * 50}
    assert (await client.post("/users/signup", json=body)).status_code == 201
    body = {**body, "login_id": "a" * 20, "password": "Aa1!" * 32}  # 아이디 20자, 비밀번호 128자
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


LIVE_SID = "live-session"  # 아래 거절 테스트에서 '살아 있는 세션'으로 쓰는 family_id (live_session 픽스처가 만든다)


def token(sub="1", key=SECRET, algorithm="HS256", expires_in=timedelta(minutes=5), with_exp=True, sid=LIVE_SID):
    now = datetime.now(timezone.utc)
    payload = {"sub": sub, "iat": now}
    if sid is not None:
        payload["sid"] = sid
    if with_exp:
        payload["exp"] = now + expires_in
    return jwt.encode(payload, key, algorithm=algorithm)


async def add_live_session(user_id: int) -> None:
    """1번 사용자에게 폐기되지 않은 갱신 토큰 행(family = LIVE_SID)을 넣어 '살아 있는 세션'을 만든다."""
    from avengers_bank.core.database import SessionLocal
    from avengers_bank.domains.users.models import RefreshToken

    async with SessionLocal() as db, db.begin():
        db.add(RefreshToken(
            user_id=user_id, family_id=LIVE_SID, token_hash="0" * 64,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        ))


async def test_helper_makes_a_valid_token(client):
    """아래 거절 테스트가 '토큰을 잘못 만들어서' 통과하는 착시가 아님을 확인하는 대조군."""
    signup = await client.post("/users/signup", json=SIGNUP)
    user_id = signup.json()["data"]["user_id"]
    await add_live_session(user_id)
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
        token(sid=None),
        token(sid="ended-or-unknown-session"),
    ],
    ids=["garbage", "expired", "wrong_key", "no_exp", "alg_none", "sub_not_number", "user_not_found",
         "no_sid", "session_not_alive"],
)
async def test_me_rejects_bad_tokens(client, bad_token):
    await client.post("/users/signup", json=SIGNUP)  # 사용자는 있다 (1번). 토큰이 문제다
    await add_live_session(1)  # 1번 사용자의 살아 있는 세션도 있다 (session_not_alive는 다른 세션 번호)
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


async def test_login_locked_after_five_failures(client):
    # C-090: 예전에는 15분 동안 429(일시 차단)였다. 지금은 5회 연속이면 잠금(403), 해제는 본인 확인으로만
    await client.post("/users/signup", json=SIGNUP)
    bad = {"login_id": SIGNUP["login_id"], "password": "wrong-password"}
    for _ in range(4):
        assert (await client.post("/users/login", json=bad)).status_code == 401

    blocked = await client.post("/users/login", json=bad)
    assert (blocked.status_code, blocked.json()["error"]["code"]) == (403, "ACCOUNT_LOCKED")
    # 맞는 비밀번호도 잠금 중에는 거절된다
    good = {"login_id": SIGNUP["login_id"], "password": SIGNUP["password"]}
    assert (await client.post("/users/login", json=good)).status_code == 403
    # 다른 아이디는 영향이 없다 (실패 5번은 이 아이디에만 쌓였다)
    other = await client.post("/users/login", json={"login_id": "nobody-here", "password": "x" * 10})
    assert other.status_code == 401


async def test_login_success_clears_failures(client):
    await client.post("/users/signup", json=SIGNUP)
    bad = {"login_id": SIGNUP["login_id"], "password": "wrong-password"}
    good = {"login_id": SIGNUP["login_id"], "password": SIGNUP["password"]}
    for _ in range(4):
        await client.post("/users/login", json=bad)
    assert (await client.post("/users/login", json=good)).status_code == 200
    for _ in range(4):  # 성공으로 초기화돼서 다시 4번까지는 막히지 않는다
        assert (await client.post("/users/login", json=bad)).status_code == 401


async def test_login_blocked_per_ip_when_guessing_many_ids(client):
    for i in range(20):
        assert (await client.post("/users/login", json={"login_id": f"user{i:03d}", "password": "x" * 10})).status_code == 401
    assert (await client.post("/users/login", json={"login_id": "user999", "password": "x" * 10})).status_code == 429


# ── 비밀번호 변경 (C-045) ─────────────────────────────────────────────


async def _auth(client):
    await client.post("/users/signup", json=SIGNUP)
    response = await client.post("/users/login", json={"login_id": SIGNUP["login_id"], "password": SIGNUP["password"]})
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


async def test_change_password_then_login_with_new_one(client):
    headers = await _auth(client)
    response = await client.patch(
        "/users/me/password", json={"current_password": SIGNUP["password"], "new_password": "NewPassw0rd!"}, headers=headers
    )
    assert response.status_code == 200 and response.json()["data"]["access_token"]  # 새 토큰 묶음을 돌려준다

    old = await client.post("/users/login", json={"login_id": SIGNUP["login_id"], "password": SIGNUP["password"]})
    new = await client.post("/users/login", json={"login_id": SIGNUP["login_id"], "password": "NewPassw0rd!"})
    assert (old.status_code, new.status_code) == (401, 200)


@pytest.mark.parametrize(
    "body, expected",
    [
        ({"current_password": "wrong-password", "new_password": "NewPassw0rd!"}, (400, "INVALID_CURRENT_PASSWORD")),
        ({"current_password": SIGNUP["password"], "new_password": SIGNUP["password"]}, (400, "SAME_PASSWORD")),
        ({"current_password": SIGNUP["password"], "new_password": "short"}, (422, "VALIDATION_ERROR")),
        ({"current_password": SIGNUP["password"], "new_password": "newpassword99"}, (422, "VALIDATION_ERROR")),
    ],
    ids=["wrong_current", "same_as_current", "new_too_short", "new_too_weak"],
)
async def test_change_password_rejections_change_nothing(client, body, expected):
    headers = await _auth(client)
    response = await client.patch("/users/me/password", json=body, headers=headers)
    assert (response.status_code, response.json()["error"]["code"]) == expected
    ok = await client.post("/users/login", json={"login_id": SIGNUP["login_id"], "password": SIGNUP["password"]})
    assert ok.status_code == 200  # 비밀번호는 그대로


async def test_change_password_requires_login(client):
    response = await client.patch("/users/me/password", json={"current_password": "x", "new_password": "NewPassw0rd!"})
    assert response.status_code == 401


async def test_change_password_wrong_current_locks_login(client):
    # C-090: 현재 비밀번호 틀림도 로그인 실패 카운터로 센다. 5번째에 로그인이 잠긴다(예전에는 429)
    headers = await _auth(client)
    bad = {"current_password": "wrong-password", "new_password": "NewPassw0rd!"}
    for _ in range(4):
        assert (await client.patch("/users/me/password", json=bad, headers=headers)).status_code == 400
    blocked = await client.patch("/users/me/password", json=bad, headers=headers)
    assert (blocked.status_code, blocked.json()["error"]["code"]) == (403, "ACCOUNT_LOCKED")
    good = {"login_id": SIGNUP["login_id"], "password": SIGNUP["password"]}
    assert (await client.post("/users/login", json=good)).status_code == 403


async def test_health_ok_and_db_failure(client, monkeypatch):
    response = await client.get("/health")
    assert (response.status_code, response.json()["data"]) == (200, {"status": "ok"})

    from types import SimpleNamespace

    import avengers_bank.main as main_module

    def broken():
        raise ConnectionError("secret-host:5432 refused")

    monkeypatch.setattr(main_module, "engine", SimpleNamespace(connect=broken))
    response = await client.get("/health")
    assert (response.status_code, response.json()["error"]["code"]) == (503, "DB_UNAVAILABLE")
    assert "secret-host" not in response.text  # 내부 오류 내용은 응답에 싣지 않는다


def test_cors_origins_setting_parses_comma_separated_list():
    from avengers_bank.core.config import Settings

    base = {"database_url": "x", "jwt_secret_key": "k" * 32}
    assert Settings(**base).cors_origin_list == ["http://127.0.0.1:5173", "http://localhost:5173"]
    custom = Settings(**base, cors_origins=" https://bank.example.com , http://localhost:3000,, ")
    assert custom.cors_origin_list == ["https://bank.example.com", "http://localhost:3000"]


async def test_cors_allows_configured_origin_only(client):
    allowed = await client.get("/", headers={"Origin": "http://localhost:5173"})
    denied = await client.get("/", headers={"Origin": "https://evil.example.com"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in denied.headers


async def test_startup_warns_when_dev_endpoints_enabled(caplog, monkeypatch):
    import avengers_bank.main as main_module

    async def start():
        async with main_module.lifespan(main_module.app):
            pass

    caplog.set_level("WARNING")
    await start()  # tests/conftest.py가 ENABLE_DEV_ENDPOINTS=true로 시작한다
    assert any("ENABLE_DEV_ENDPOINTS" in r.message for r in caplog.records)

    caplog.clear()
    monkeypatch.setattr(main_module, "get_settings", lambda: type("S", (), {"enable_dev_endpoints": False})())
    await start()
    assert not any("ENABLE_DEV_ENDPOINTS" in r.message for r in caplog.records)


# ── 회원 정보 입력 규칙: 아이디·이름·전화번호·닉네임·비밀번호 강도, 422 한국어 메시지 ──


async def test_login_id_is_trimmed_and_lowercased_on_signup_and_login(client):
    signup = await client.post("/users/signup", json={**SIGNUP, "login_id": "  IronMan_7 "})
    assert signup.status_code == 201 and signup.json()["data"]["login_id"] == "ironman_7"
    for login_id in ("ironman_7", " IRONMAN_7 ", "IronMan_7"):  # 모두 같은 계정
        login = await client.post("/users/login", json={"login_id": login_id, "password": SIGNUP["password"]})
        assert login.status_code == 200, login_id


async def test_login_id_duplicate_check_ignores_case(client):
    assert (await client.post("/users/signup", json={**SIGNUP, "login_id": "Admin"})).status_code == 201
    again = await client.post("/users/signup", json={**SIGNUP, "login_id": "admin"})
    assert (again.status_code, again.json()["error"]["code"]) == (409, "LOGIN_ID_ALREADY_EXISTS")


@pytest.mark.parametrize("login_id", ["iron-man", "ab", "x" * 30, "아이언맨!", "a b c d"])
async def test_login_does_not_check_login_id_format(client, login_id):
    """로그인은 형식 검사를 하지 않는다: 422가 아니라 401이어야 아이디 규칙이 새지 않는다."""
    response = await client.post("/users/login", json={"login_id": login_id, "password": "x"})
    assert (response.status_code, response.json()["error"]["code"]) == (401, "INVALID_CREDENTIALS")


@pytest.mark.parametrize(
    "phone, saved",
    [("01012345678", "010-1234-5678"), ("010 1234 5678", "010-1234-5678"), (" 010-1234-5678 ", "010-1234-5678"),
     ("0111234567", "011-123-4567"), ("019-123-4567", "019-123-4567")],
)
async def test_phone_is_normalized(client, phone, saved):
    response = await client.post("/users/signup", json={**SIGNUP, "phone": phone})
    assert response.status_code == 201 and response.json()["data"]["phone"] == saved


async def test_name_and_nickname_are_trimmed(client):
    response = await client.post("/users/signup", json={**SIGNUP, "name": "  토니  ", "nick_name": "   "})
    data = response.json()["data"]
    assert (response.status_code, data["name"], data["nick_name"]) == (201, "토니", None)


async def test_signup_rejects_password_same_as_login_id(client):
    body = {**SIGNUP, "login_id": "tony_1234", "password": "TONY_1234"}  # 대소문자만 다른 것도 거절
    response = await client.post("/users/signup", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["msg"] == "비밀번호는 아이디와 같을 수 없습니다."


@pytest.mark.parametrize("password", ["Passw0rd가", "Pass w0rd!", "Passw0rd！"])  # 한글, 공백, 전각 느낌표
async def test_password_allows_only_keyboard_characters(client, password):
    """은행 앱처럼 영문·숫자·키보드 특수문자만. 한글·공백·전각 문자는 특수문자로 쳐 주지 않고 거절한다."""
    response = await client.post("/users/signup", json={**SIGNUP, "password": password})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["msg"] == "비밀번호는 영문, 숫자, 특수문자(!@#$ 등)만 사용할 수 있습니다."


async def test_update_me_uses_same_rules(client, make_user):
    headers = await make_user("ironman")
    token = await phone_token(client, "010-9999-8888", "CHANGE_PHONE", headers)
    response = await client.patch(
        "/users/me",
        json={"name": "  페퍼 ", "phone": "01099998888", "nick_name": "", "phone_verification_token": token},
        headers=headers,
    )
    data = response.json()["data"]
    assert (data["name"], data["phone"], data["nick_name"]) == ("페퍼", "010-9999-8888", None)
    bad = await client.patch("/users/me", json={"phone": "02-123-4567"}, headers=headers)
    assert bad.json()["error"]["details"][0]["msg"] == "휴대폰 번호를 010-1234-5678 형식으로 입력해 주세요."


async def test_old_weak_password_still_works_for_login_and_change(client):
    """예전 규칙으로 만든 계정(약한 비밀번호·대문자 아이디)도 로그인과 비밀번호 변경은 된다."""
    from avengers_bank.core.database import SessionLocal
    from avengers_bank.domains.users.models import User

    async with SessionLocal() as db, db.begin():
        db.add(User(login_id="legacy", hashed_password=password_hash.hash("password1234"), name="옛날", phone="010-0000-0000"))
    login = await client.post("/users/login", json={"login_id": "legacy", "password": "password1234"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
    change = await client.patch(
        "/users/me/password", json={"current_password": "password1234", "new_password": "NewPassw0rd!"}, headers=headers
    )
    assert change.status_code == 200


@pytest.mark.parametrize(
    "url, body, expected",
    [
        ("/users/signup", {**SIGNUP, "phone": "1" * 21}, "휴대폰 번호는 20자 이하로 입력해 주세요."),
        ("/users/signup", {**SIGNUP, "password": "password!!"}, "비밀번호는 영문, 숫자, 특수문자를 모두 포함해야 합니다."),
        ("/users/signup", {**SIGNUP, "password": "Pa1!"}, "비밀번호는 8자 이상 입력해 주세요."),
        ("/users/signup", {**SIGNUP, "login_id": "Iron-Man"}, "아이디는 영문 소문자, 숫자, 밑줄(_)만 4~20자로 입력해 주세요."),
        ("/users/signup", {**SIGNUP, "name": "  "}, "이름을 입력해 주세요."),
        ("/users/signup", {k: v for k, v in SIGNUP.items() if k != "phone"}, "필수 항목입니다: 휴대폰 번호"),
        ("/users/login", {"login_id": "", "password": "x"}, "아이디를 입력해 주세요."),
    ],
    ids=["phone_long", "password_weak", "password_short", "login_id_format", "name_blank", "phone_missing", "login_empty"],
)
async def test_validation_messages_are_korean_sentences(client, url, body, expected):
    response = await client.post(url, json=body)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["message"] == "입력값을 확인해 주세요."
    assert error["details"][0]["msg"] == expected
    assert not any(word in response.text for word in ("String should", "Field required", "Value error"))


async def test_validation_message_for_forbidden_and_unknown_fields(client, make_user):
    headers = await make_user("ironman")
    details = (await client.patch("/users/me", json={"login_id": "x", "foo": 1}, headers=headers)).json()["error"]["details"]
    assert [d["msg"] for d in details] == ["변경할 수 없는 항목입니다: 아이디", "변경할 수 없는 항목입니다: 입력값"]
    assert [d["type"] for d in details] == ["extra_forbidden", "extra_forbidden"]  # 응답 구조는 그대로


def test_korean_message_covers_number_and_date_errors():
    from avengers_bank.core.exception_handlers import korean_message

    assert korean_message({"type": "greater_than", "loc": ("body", "amount"), "msg": "", "ctx": {"gt": 0}}) == "금액은 0보다 커야 합니다."
    assert korean_message(
        {"type": "greater_than_equal", "loc": ("body", "initial_amount"), "msg": "", "ctx": {"ge": 1000000}}
    ) == "가입 금액은 1,000,000 이상이어야 합니다."
    assert korean_message({"type": "int_parsing", "loc": ("body", "monthly_payment"), "msg": ""}) == "매월 납입액은 정수로 입력해 주세요."
    assert korean_message({"type": "date_parsing", "loc": ("body", "maturity_date"), "msg": ""}) == (
        "만기일은 YYYY-MM-DD 형식의 날짜로 입력해 주세요."
    )
    assert korean_message({"type": "missing", "loc": ("body", "from_checking_account_id"), "msg": ""}) == "필수 항목입니다: 출금 계좌"
    assert korean_message({"type": "something_new", "loc": ("body", "weird"), "msg": ""}) == "입력값을 확인해 주세요: 입력값"
