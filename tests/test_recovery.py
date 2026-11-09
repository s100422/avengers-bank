"""계정 복구 (아이디·비밀번호 찾기)와 계좌 비밀번호 설정·재설정.

은행형 복구: 계좌번호 + 계좌 비밀번호(아는 것) + 등록 휴대폰 인증번호(가진 것). /recovery/start는 정보가 틀려도 같은 응답.
같은 계좌 카운터의 동시성(PostgreSQL)은 scripts/pg_account_password_concurrency.py가 본다.
"""

import pytest
from sqlalchemy import func, select, update

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.security import verify_password
from avengers_bank.domains.accounts.models import CheckingAccount
from avengers_bank.domains.recovery.service import mask_login_id
from avengers_bank.domains.users.models import User, UserDevice
from avengers_bank.domains.verification.sms import dev_inbox, dev_messages
from tests.cookie_helpers import cookie_header, session_of
from tests.verification_helpers import phone_token, read_code

pytestmark = pytest.mark.anyio

PASSWORD, NEW_PASSWORD = "Passw0rd!23", "N3wPassw0rd!"
TONY_PHONE, BRUCE_PHONE = "010-1111-2222", "010-3333-4444"
TONY_PW, BRUCE_PW, WRONG = "1357", "2468", "0007"
START_MESSAGE = "입력하신 정보가 맞으면 등록된 휴대폰으로 인증번호를 보냈습니다."


def error(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


async def checking_row(account_id: int) -> CheckingAccount:
    async with SessionLocal() as db:
        return await db.get(CheckingAccount, account_id)


async def login(client, login_id="ironman", password=PASSWORD):
    return await client.post("/users/login", json={"login_id": login_id, "password": password})


@pytest.fixture
async def bank(client, account_products):
    """토니(ironman, 입출금 1번 비밀번호 1357), 브루스(hulk, 입출금 2번 2468). 번호가 서로 달라 발송 제한이 섞이지 않는다."""
    out = {}
    for name, login_id, phone, pw in (("tony", "ironman", TONY_PHONE, TONY_PW), ("bruce", "hulk", BRUCE_PHONE, BRUCE_PW)):
        body = {"login_id": login_id, "password": PASSWORD, "name": name, "phone": phone}
        assert (await client.post("/users/signup", json=body)).status_code == 201
        headers = {"Authorization": f"Bearer {(await login(client, login_id)).json()['data']['access_token']}"}
        account = await client.post("/accounts/checking", json={"product_id": 1, "account_password": pw}, headers=headers)
        assert account.status_code == 201, account.text
        out[name] = {"headers": headers, "account": account.json()["data"]}
    dev_inbox.clear()  # 가입 인증 문자는 지워 두고, 이 테스트들이 보낸 문자만 센다
    return out


async def start(client, account_num, account_password, purpose="FIND_LOGIN_ID", login_id=None):
    body = {"purpose": purpose, "account_num": account_num, "account_password": account_password}
    if login_id is not None:
        body["login_id"] = login_id
    return await client.post("/recovery/start", json=body)


async def verify(client, recovery_token, code):
    return await client.post("/recovery/verify", json={"recovery_token": recovery_token, "code": code})


def wrong_code(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


async def reset_token(client, bank) -> str:
    started = await start(client, bank["tony"]["account"]["account_num"], TONY_PW, "PASSWORD_RESET", "ironman")
    verified = await verify(client, started.json()["data"]["recovery_token"], await read_code(client, TONY_PHONE))
    assert verified.status_code == 200, verified.text
    assert verified.json()["data"]["expires_in"] == 600
    return verified.json()["data"]["reset_token"]


# ── 아이디 찾기 ───────────────────────────────────────────────────────


def test_mask_login_id():
    assert [mask_login_id(x) for x in ("demo3", "abcd", "ironman", "abc")] == ["de**3", "ab*d", "ir****n", "a**"]


async def test_find_login_id(client, bank):
    started = await start(client, bank["tony"]["account"]["account_num"], TONY_PW)
    assert started.status_code == 200
    assert started.json()["message"] == START_MESSAGE
    assert started.json()["data"]["expires_in"] == 600
    token = started.json()["data"]["recovery_token"]

    response = await verify(client, token, await read_code(client, TONY_PHONE))
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {"masked_login_id": "ir****n"}
    # 전체 아이디는 등록 휴대폰으로만
    assert dev_messages(TONY_PHONE)[0][0] == (
        "[AvengersBank] 아이디: ironman. 본인이 요청하지 않았다면 고객센터로 연락해 주세요."
    )
    assert "ironman" not in response.text
    # 한 번 쓴 인증은 다시 쓸 수 없다
    assert error(await verify(client, token, "000000")) == (400, "VERIFICATION_EXPIRED")


async def test_start_response_is_identical_whatever_is_wrong(client, bank):
    tony_num = bank["tony"]["account"]["account_num"]
    async with SessionLocal() as db, db.begin():  # 브루스 계좌: 잠금 상태로
        await db.execute(update(CheckingAccount).where(CheckingAccount.checking_account_id == 2).values(
            password_failed_count=5, password_locked_at=CheckingAccount.created_at))
    cases = {
        "정상": (tony_num, TONY_PW, "FIND_LOGIN_ID", None),
        "계좌 없음": ("110-000-000000", TONY_PW, "FIND_LOGIN_ID", None),
        "비밀번호 틀림": (tony_num, WRONG, "FIND_LOGIN_ID", None),
        "잠긴 계좌(맞는 비밀번호)": (bank["bruce"]["account"]["account_num"], BRUCE_PW, "FIND_LOGIN_ID", None),
        "없는 아이디": (tony_num, TONY_PW, "PASSWORD_RESET", "nobody"),
        "남의 아이디 + 내 계좌": (tony_num, TONY_PW, "PASSWORD_RESET", "hulk"),
    }
    shapes = {}
    for label, args in cases.items():
        response = await start(client, *args)
        body = response.json()
        shapes[label] = (response.status_code, body["message"], tuple(sorted(body["data"])), body["data"]["expires_in"],
                         len(body["data"]["recovery_token"]))
    # 같은 purpose끼리는 완전히 같은 모양 (토큰 길이까지. purpose 문자열 길이만큼은 토큰 길이가 다르다)
    assert len({(cases[label][2], shape) for label, shape in shapes.items()}) == 2, shapes
    # 문자는 정상 1건만 (토니에게). 브루스에게는 아무것도 가지 않았다
    assert len(dev_messages(TONY_PHONE)) == 1
    assert dev_messages(BRUCE_PHONE) == []

    # 미설정 계좌도 같은 응답 (마이그레이션 전 계좌 = NULL)
    async with SessionLocal() as db, db.begin():
        await db.execute(update(CheckingAccount).where(CheckingAccount.checking_account_id == 1).values(password_hash=None))
    unset = await start(client, tony_num, TONY_PW)
    assert (unset.status_code, unset.json()["message"]) == (200, START_MESSAGE)
    assert len(dev_messages(TONY_PHONE)) == 1


async def test_fake_token_fails_exactly_like_a_wrong_code(client, bank):
    real = (await start(client, bank["tony"]["account"]["account_num"], TONY_PW)).json()["data"]["recovery_token"]
    code = await read_code(client, TONY_PHONE)
    fake = (await start(client, bank["tony"]["account"]["account_num"], WRONG)).json()["data"]["recovery_token"]

    async def five_wrong_then_one(token):
        return [(r.status_code, r.json()["error"]["code"], r.json()["error"]["message"])
                for r in [await verify(client, token, wrong_code(code)) for _ in range(6)]]

    real_errors, fake_errors = await five_wrong_then_one(real), await five_wrong_then_one(fake)
    assert real_errors == fake_errors
    assert real_errors[0][2] == "인증번호가 올바르지 않습니다. (1/5)"
    assert real_errors[4][2].endswith("(5/5)")
    assert real_errors[5][1] == "VERIFICATION_EXPIRED"
    # 위조·깨진 토큰은 만료로 (다시 시작하면 된다)
    assert error(await verify(client, real[:-2] + "xx", code)) == (400, "VERIFICATION_EXPIRED")


# ── 비밀번호 찾기 ─────────────────────────────────────────────────────


async def test_password_reset_revokes_devices_and_clears_both_locks(client, bank):
    """기기 등록(B1): 재설정은 두 채널의 잠금을 모두 풀고 등록 기기를 모두 해제한다(새 비밀번호도 휴대폰 인증을 다시 거친다)."""
    assert (await login(client)).status_code == 200  # 이 브라우저는 ironman의 등록 기기가 된다(BankClient가 인증을 자동으로 끝낸다)
    no_cookie = {"Cookie": ""}
    for headers in (None, no_cookie):  # 등록 기기 채널, 새 기기 채널을 둘 다 잠근다
        for _ in range(5):
            await client.post("/users/login", json={"login_id": "ironman", "password": "Wrong0pass!"}, headers=headers)
    async with SessionLocal() as db:
        user = await db.get(User, 1)
        assert user.login_locked_at is not None and user.device_login_locked_at is not None
        assert await db.scalar(select(func.count()).select_from(UserDevice).where(UserDevice.user_id == 1, UserDevice.revoked_at.is_(None))) == 2  # bank가 가입하며 한 번, 위 로그인(보관함은 hulk 쿠키)이 한 번

    token = await reset_token(client, bank)
    response = await client.post("/recovery/password", json={"reset_token": token, "new_password": NEW_PASSWORD})
    assert response.status_code == 200, response.text
    async with SessionLocal() as db:
        user = await db.get(User, 1)
        assert (user.failed_login_count, user.login_locked_at) == (0, None)
        assert (user.device_failed_login_count, user.device_login_locked_at) == (0, None)
        rows = list(await db.scalars(select(UserDevice)))
    assert {(d.user_id, d.revoked_at is not None) for d in rows} == {(1, True), (2, False)}  # 다른 사용자의 기기는 그대로
    client.auto_device_verification = False
    again = await login(client, password=NEW_PASSWORD)  # 낡은 기기 쿠키는 새 기기 취급
    assert again.json()["data"]["status"] == "DEVICE_VERIFICATION_REQUIRED"


async def test_password_reset_unlocks_login_and_revokes_all_sessions(client, bank):
    refresh = session_of(await login(client))["refresh_token"]
    for _ in range(4):
        assert error(await login(client, password="Wrong0pass!")) == (401, "INVALID_CREDENTIALS")
    assert error(await login(client, password="Wrong0pass!")) == (403, "ACCOUNT_LOCKED")
    assert error(await login(client)) == (403, "ACCOUNT_LOCKED")  # 잠기면 맞는 비밀번호도 거절

    token = await reset_token(client, bank)
    response = await client.post("/recovery/password", json={"reset_token": token, "new_password": NEW_PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json() == {"data": None, "message": "비밀번호를 재설정했습니다. 새 비밀번호로 로그인해 주세요."}
    assert "token" not in response.text  # 자동 로그인 없음

    async with SessionLocal() as db:
        user = await db.get(User, 1)
        assert (user.failed_login_count, user.login_locked_at) == (0, None)
    assert dev_messages(TONY_PHONE)[0][0] == (
        "[AvengersBank] 비밀번호가 재설정되었습니다. 본인이 아니라면 바로 고객센터로 연락해 주세요."
    )
    assert (await client.post("/users/token/refresh", headers=cookie_header(refresh))).status_code == 401
    assert error(await login(client)) == (401, "INVALID_CREDENTIALS")
    assert (await login(client, password=NEW_PASSWORD)).status_code == 200

    # reset_token은 1회용
    again = await client.post("/recovery/password", json={"reset_token": token, "new_password": "An0ther!pass"})
    assert error(again) == (400, "INVALID_VERIFICATION_TOKEN")


async def test_password_reset_rules(client, bank):
    token = await reset_token(client, bank)
    weak = await client.post("/recovery/password", json={"reset_token": token, "new_password": "password"})
    assert weak.status_code == 422
    same = await client.post("/recovery/password", json={"reset_token": token, "new_password": PASSWORD})
    assert error(same) == (400, "SAME_PASSWORD")
    # 규칙 위반은 증표를 쓰지 않는다: 고쳐서 같은 증표로 다시 보낼 수 있다
    ok = await client.post("/recovery/password", json={"reset_token": token, "new_password": NEW_PASSWORD})
    assert ok.status_code == 200, ok.text
    # FIND_LOGIN_ID 증표 등 다른 용도의 토큰은 reset_token으로 못 쓴다
    signup_token = await phone_token(client, "010-5555-6666", exempt=True)
    assert error(await client.post(
        "/recovery/password", json={"reset_token": signup_token, "new_password": NEW_PASSWORD}
    )) == (400, "INVALID_VERIFICATION_TOKEN")


async def test_password_reset_requires_login_id(client, bank):
    response = await start(client, bank["tony"]["account"]["account_num"], TONY_PW, "PASSWORD_RESET")
    assert response.status_code == 422


async def test_other_login_id_with_my_account_sends_nothing(client, bank):
    response = await start(client, bank["tony"]["account"]["account_num"], TONY_PW, "PASSWORD_RESET", "hulk")
    assert response.status_code == 200
    assert dev_messages(TONY_PHONE) == [] and dev_messages(BRUCE_PHONE) == []
    # 가짜 토큰이므로 어떤 인증번호로도 통과하지 못한다
    assert error(await verify(client, response.json()["data"]["recovery_token"], "123456"))[1] == "INVALID_VERIFICATION_CODE"


async def test_wrong_account_password_on_start_counts_and_locks_the_account(client, bank):
    tony_num = bank["tony"]["account"]["account_num"]
    for n in range(1, 6):
        assert (await start(client, tony_num, WRONG)).status_code == 200
        assert (await checking_row(1)).password_failed_count == n  # 같은 응답이지만 DB에는 커밋된다
    assert (await checking_row(1)).password_locked_at is not None

    # 잠긴 뒤: 맞는 비밀번호로도 인증번호가 오지 않고, 이체도 403
    assert (await start(client, tony_num, TONY_PW)).status_code == 200
    assert dev_messages(TONY_PHONE) == []
    transfer = {"from_checking_account_id": 1, "to_account_num": bank["bruce"]["account"]["account_num"],
                "amount": 1, "account_password": TONY_PW}
    assert error(await client.post("/transfers", json=transfer, headers=bank["tony"]["headers"])) == (
        403, "ACCOUNT_PASSWORD_LOCKED")


async def test_ip_limit_429_and_phone_limit_is_silent(client, bank):
    tony_num = bank["tony"]["account"]["account_num"]
    # 번호당 15분 3번: 4번째는 429가 아니라 같은 200 (429면 '정보가 맞았다'가 드러난다), 문자는 3통만
    for _ in range(4):
        response = await start(client, tony_num, TONY_PW)
        assert (response.status_code, response.json()["message"]) == (200, START_MESSAGE)
    assert len(dev_messages(TONY_PHONE)) == 3
    # IP당 15분 10번: 정보가 틀린 요청도 센다
    for _ in range(6):
        assert (await start(client, "110-000-000000", WRONG)).status_code == 200
    assert error(await start(client, "110-000-000000", WRONG)) == (429, "TOO_MANY_VERIFICATION_REQUESTS")


# ── 계좌 비밀번호 설정·재설정 ────────────────────────────────────────


async def account_password_token(client, headers, *, phone_in_body=TONY_PHONE) -> str:
    return await phone_token(client, phone_in_body, "ACCOUNT_PASSWORD_RESET", headers, exempt=True)


async def set_password(client, headers, account_id, token, new="4680"):
    return await client.post(
        f"/accounts/checking/{account_id}/password",
        json={"phone_verification_token": token, "new_account_password": new}, headers=headers,
    )


async def test_send_for_me_account_password_reset_goes_to_registered_phone(client, bank):
    headers = bank["tony"]["headers"]
    sent = await client.post(
        "/verification/phone/send-for-me",
        json={"purpose": "ACCOUNT_PASSWORD_RESET", "phone": "010-9999-9999"}, headers=headers,
    )
    assert sent.status_code == 200
    assert dev_messages("010-9999-9999") == [] and len(dev_messages(TONY_PHONE)) == 1  # 본문 번호는 무시
    no_phone = await client.post("/verification/phone/send-for-me", json={"purpose": "ACCOUNT_PASSWORD_RESET"}, headers=headers)
    assert no_phone.status_code == 200
    assert (await client.post("/verification/phone/send-for-me", json={"purpose": "CHANGE_PHONE"}, headers=headers)).status_code == 422


async def test_reset_account_password(client, bank):
    tony = bank["tony"]["headers"]
    async with SessionLocal() as db, db.begin():  # 5회 틀려 잠긴 상태
        await db.execute(update(CheckingAccount).where(CheckingAccount.checking_account_id == 1).values(
            password_failed_count=5, password_locked_at=CheckingAccount.created_at))

    async def flags(path):
        response = await client.get(path, headers=tony)
        assert "password_hash" not in response.text and "failed" not in response.text  # 상태만, 해시·횟수는 안 나간다
        data = response.json()["data"]
        data = data[0] if isinstance(data, list) else data
        return data["password_set"], data["password_locked"]

    assert await flags("/accounts/checking/1") == (True, True)
    assert await flags("/accounts") == (True, True)

    # 증표 없음·가짜 증표
    assert (await client.post("/accounts/checking/1/password", json={"new_account_password": "4680"}, headers=tony)).status_code == 422
    assert error(await set_password(client, tony, 1, "not-a-token")) == (400, "INVALID_VERIFICATION_TOKEN")

    token = await account_password_token(client, tony)
    assert error(await set_password(client, tony, 2, token)) == (404, "ACCOUNT_NOT_FOUND")  # 남의 계좌
    assert (await set_password(client, tony, 1, token, new="1234")).status_code == 422  # 형식 규칙
    response = await set_password(client, tony, 1, token)  # 404·422에 쓰이지 않은 같은 증표
    assert response.status_code == 200, response.text
    assert response.json() == {"data": None, "message": "계좌 비밀번호를 설정했습니다."}
    row = await checking_row(1)
    assert (row.password_failed_count, row.password_locked_at) == (0, None)
    assert verify_password("4680", row.password_hash)
    assert "비밀번호가 설정되었습니다" in dev_messages(TONY_PHONE)[0][0]
    assert error(await set_password(client, tony, 1, token)) == (400, "INVALID_VERIFICATION_TOKEN")  # 1회용
    assert await flags("/accounts/checking/1") == (True, False)

    # 처음 설정(NULL)도 같은 API
    async with SessionLocal() as db, db.begin():
        await db.execute(update(CheckingAccount).where(CheckingAccount.checking_account_id == 1).values(password_hash=None))
    assert await flags("/accounts") == (False, False)
    assert (await set_password(client, tony, 1, await account_password_token(client, tony), new="9135")).status_code == 200
    assert verify_password("9135", (await checking_row(1)).password_hash)


async def test_reset_account_password_rejects_other_purpose_or_other_user(client, bank):
    tony, bruce = bank["tony"]["headers"], bank["bruce"]["headers"]
    change_phone = await phone_token(client, "010-7777-8888", "CHANGE_PHONE", tony, exempt=True)
    assert error(await set_password(client, tony, 1, change_phone)) == (400, "INVALID_VERIFICATION_TOKEN")
    # 브루스가 받은 증표로 토니 계좌? → 브루스에게 토니 계좌는 404, 토니가 브루스 증표를 쓰면 증표가 안 맞는다
    bruce_token = await account_password_token(client, bruce, phone_in_body=BRUCE_PHONE)
    assert error(await set_password(client, tony, 1, bruce_token)) == (400, "INVALID_VERIFICATION_TOKEN")
    assert verify_password(TONY_PW, (await checking_row(1)).password_hash)
