"""회원 탈퇴: 조건(예금·적금 해지, 입출금 잔액 0, 신용카드 미결제 0), 본인 확인(비밀번호 + 휴대폰), 소프트 삭제.

'잔액 0 확인 직후 남이 입금'하는 경쟁은 SQLite가 FOR UPDATE를 무시해 여기서 볼 수 없다 → scripts/pg_withdrawal_concurrency.py.
"""

import pytest
from sqlalchemy import func, select, update

from avengers_bank.core.database import SessionLocal
from tests.cookie_helpers import cookie_header, session_of, set_cookies
from avengers_bank.domains.accounts.models import CheckingAccount, CheckingAccountHistory
from avengers_bank.domains.agent.models import AgentConversation, AgentMessage, TransferDraft
from avengers_bank.domains.cards.models import CreditCard, DebitCard
from avengers_bank.domains.products.models import CardProduct
from avengers_bank.domains.terms.models import TermsConsent
from avengers_bank.domains.users.models import RefreshToken, User, UserDevice
from avengers_bank.domains.verification.models import VerificationCode
from avengers_bank.domains.verification.sms import dev_inbox, dev_messages
from tests.helpers import FUTURE, open_deposit
from tests.verification_helpers import phone_token

pytestmark = pytest.mark.anyio

PASSWORD = "Passw0rd!23"
TONY_PHONE, BRUCE_PHONE = "010-1111-2222", "010-3333-4444"
DONE = "회원 탈퇴가 완료되었습니다. 그동안 이용해 주셔서 감사합니다."


def error(response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


async def login(client, login_id="ironman", password=PASSWORD):
    return await client.post("/users/login", json={"login_id": login_id, "password": password})


@pytest.fixture
async def bank(client, account_products):
    """토니(ironman, 입출금 1번)·브루스(hulk, 입출금 2번, 10만 원). 카드 상품: 신용 1번, 체크 2번."""
    async with SessionLocal() as db, db.begin():
        db.add_all([
            CardProduct(type="CREDIT", name="신용", description="d", credit_limit=1_000_000),
            CardProduct(type="DEBIT", name="체크", description="d"),
        ])
    out = {}
    for name, login_id, phone in (("tony", "ironman", TONY_PHONE), ("bruce", "hulk", BRUCE_PHONE)):
        body = {"login_id": login_id, "password": PASSWORD, "name": name, "nick_name": "닉", "phone": phone}
        assert (await client.post("/users/signup", json=body)).status_code == 201
        tokens = session_of(await login(client, login_id))
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        account = (await client.post("/accounts/checking", json={"product_id": 1}, headers=headers)).json()["data"]
        out[name] = {"headers": headers, "refresh": tokens["refresh_token"], "account": account}
    await client.post("/dev/accounts/checking/2/charge", json={"amount": 100_000}, headers=out["bruce"]["headers"])
    return out


async def withdrawal_token(client, headers, phone=TONY_PHONE, purpose="WITHDRAWAL"):
    return await phone_token(client, phone, purpose, headers=headers, exempt=True)


async def withdraw(client, headers, token, password=PASSWORD):
    body = {"current_password": password, "phone_verification_token": token}
    return await client.post("/users/me/withdrawal", json=body, headers=headers)


async def user_row(login_id="ironman") -> User:
    async with SessionLocal() as db:
        return await db.scalar(select(User).where(User.login_id == login_id))


async def active_devices(user_id: int) -> int:
    async with SessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(UserDevice).where(
            UserDevice.user_id == user_id, UserDevice.revoked_at.is_(None)))


async def test_requires_login(client):
    assert (await client.get("/users/me/withdrawal")).status_code == 401
    assert (await client.post("/users/me/withdrawal", json={})).status_code == 401


async def test_blockers_list_what_to_do_first_and_lift_one_by_one(client, bank):
    tony = bank["tony"]["headers"]
    await client.post("/dev/accounts/checking/1/charge", json={"amount": 312_000}, headers=tony)
    assert (await open_deposit(client, tony, 300_000, from_id=1)).status_code == 201  # 남은 잔액 12,000원
    savings = {"product_id": 3, "monthly_payment": 10_000, "monthly_deposit_date": 25, "maturity_date": FUTURE}
    assert (await client.post("/accounts/savings", json=savings, headers=tony)).status_code == 201
    card = await client.post("/cards/credit", json={"product_id": 1, "checking_account_id": 1, "payment_date": 14}, headers=tony)
    card = card.json()["data"]
    pay = {"place_of_use": "가게", "used_amount": 5_000}
    assert (await client.post(f"/cards/credit/{card['card_id']}/payments", json=pay, headers=tony)).status_code == 201

    status = (await client.get("/users/me/withdrawal", headers=tony)).json()["data"]
    num = bank["tony"]["account"]["account_num"]
    assert status["can_withdraw"] is False
    assert [b["code"] for b in status["blockers"]] == ["ACTIVE_DEPOSIT", "ACTIVE_SAVINGS", "CHECKING_BALANCE", "CARD_UNPAID"]
    deposit, savings_b, checking, unpaid = status["blockers"]
    assert (deposit["account_type"], deposit["account_id"]) == ("deposit", 1)
    assert deposit["message"].startswith("해지하지 않은 예금이 있습니다: 120-")
    assert (savings_b["account_type"], savings_b["account_id"]) == ("savings", 1)
    assert checking == {"code": "CHECKING_BALANCE", "message": f"잔액이 남은 입출금 계좌가 있습니다: {num}(12,000원)",
                        "account_type": "checking", "account_id": 1, "card_id": None}
    assert unpaid["card_id"] == card["card_id"] and unpaid["message"].endswith("(5,000원)")

    # 막혀 있으면 비밀번호를 세기 전에 400 (틀린 비밀번호여도 카운트가 늘지 않는다)
    blocked = await withdraw(client, tony, "x", password="wrong")
    assert error(blocked) == (400, "WITHDRAWAL_BLOCKED")
    assert blocked.json()["error"]["message"] == "탈퇴할 수 없습니다. " + deposit["message"] + " 외 3건"
    assert (await user_row()).failed_login_count == 0

    # 하나씩 풀면 목록에서 빠진다
    close = {"to_checking_account_id": 1}
    assert (await client.post("/accounts/deposit/1/close", json=close, headers=tony)).status_code == 200
    assert (await client.post("/accounts/savings/1/close", json=close, headers=tony)).status_code == 200
    codes = [b["code"] for b in (await client.get("/users/me/withdrawal", headers=tony)).json()["data"]["blockers"]]
    assert codes == ["CHECKING_BALANCE", "CARD_UNPAID"]
    async with SessionLocal() as db, db.begin():  # 카드 대금 납부(청구서 흐름)는 test_cards가 본다: 여기서는 갚은 상태로
        await db.execute(update(CreditCard).values(outstanding_amount=0))
    balance = (await client.get("/accounts/checking/1", headers=tony)).json()["data"]["balance"]
    to_bruce = {"from_checking_account_id": 1, "to_account_num": bank["bruce"]["account"]["account_num"], "amount": balance}
    assert (await client.post("/transfers", json=to_bruce, headers=tony)).status_code == 201
    assert (await client.get("/users/me/withdrawal", headers=tony)).json()["data"] == {"can_withdraw": True, "blockers": []}


async def test_wrong_password_counts_like_login_and_locks_at_five(client, bank):
    tony = bank["tony"]["headers"]
    token = await withdrawal_token(client, tony)
    for i in range(1, 5):
        assert error(await withdraw(client, tony, token, password="Wrong!123")) == (400, "INVALID_CURRENT_PASSWORD")
        assert (await user_row()).failed_login_count == i
    assert error(await withdraw(client, tony, token, password="Wrong!123")) == (403, "ACCOUNT_LOCKED")
    assert error(await withdraw(client, tony, token)) == (403, "ACCOUNT_LOCKED")  # 잠기면 맞는 비밀번호도
    assert error(await login(client)) == (403, "ACCOUNT_LOCKED")
    assert (await user_row()).deleted_at is None


async def test_correct_password_resets_count_even_if_token_is_bad(client, bank):
    tony = bank["tony"]["headers"]
    await withdraw(client, tony, "x", password="Wrong!123")
    assert error(await withdraw(client, tony, "not-a-token")) == (400, "INVALID_VERIFICATION_TOKEN")
    assert (await user_row()).failed_login_count == 0


async def test_rejects_missing_other_purpose_and_other_users_token(client, bank):
    tony, bruce = bank["tony"]["headers"], bank["bruce"]["headers"]
    missing = await client.post("/users/me/withdrawal", json={"current_password": PASSWORD}, headers=tony)
    assert missing.status_code == 422
    other_purpose = await withdrawal_token(client, tony, purpose="ACCOUNT_PASSWORD_RESET")
    assert error(await withdraw(client, tony, other_purpose)) == (400, "INVALID_VERIFICATION_TOKEN")
    bruces = await withdrawal_token(client, bruce, phone=BRUCE_PHONE)
    assert error(await withdraw(client, tony, bruces)) == (400, "INVALID_VERIFICATION_TOKEN")
    assert (await user_row()).deleted_at is None and (await user_row("hulk")).deleted_at is None
    async with SessionLocal() as db:  # 브루스의 증표는 쓰이지 않았다
        assert await db.scalar(select(VerificationCode.consumed_at).where(VerificationCode.user_id == 2,
                                                                          VerificationCode.purpose == "WITHDRAWAL")) is None


async def test_send_for_me_withdrawal_goes_to_registered_phone(client, bank):
    dev_inbox.clear()
    sent = await client.post(
        "/verification/phone/send-for-me", json={"purpose": "WITHDRAWAL", "phone": "010-9999-9999"},
        headers=bank["tony"]["headers"],
    )
    assert sent.status_code == 200
    assert dev_messages("010-9999-9999") == [] and len(dev_messages(TONY_PHONE)) == 1


async def test_withdrawal_success(client, bank):
    tony, bruce = bank["tony"]["headers"], bank["bruce"]["headers"]
    tony_num = bank["tony"]["account"]["account_num"]
    # 거래 기록 하나(받고 돌려줌 → 잔액 0), 카드 2장(미결제 0), AI 대화·초안
    await client.post("/transfers", json={"from_checking_account_id": 2, "to_account_num": tony_num, "amount": 1_000}, headers=bruce)
    back = {"from_checking_account_id": 1, "to_account_num": bank["bruce"]["account"]["account_num"], "amount": 1_000}
    assert (await client.post("/transfers", json=back, headers=tony)).status_code == 201
    await client.post("/cards/credit", json={"product_id": 1, "checking_account_id": 1, "payment_date": 14}, headers=tony)
    await client.post("/cards/debit", json={"product_id": 2, "checking_account_id": 1}, headers=tony)
    async with SessionLocal() as db, db.begin():
        conversation = AgentConversation(user_id=1)
        db.add(conversation)
        await db.flush()
        db.add(AgentMessage(conversation_id=conversation.conversation_id, role="user", content="잔액 알려 줘"))
        db.add(TransferDraft(
            draft_id="d" * 43, user_id=1, from_checking_account_id=1, to_account_num="110-000-000000",
            recipient_name="누구", amount=1, expires_at=func.now(),
        ))
    async with SessionLocal() as db:
        histories_before = await db.scalar(select(func.count()).select_from(CheckingAccountHistory).where(
            CheckingAccountHistory.checking_account_id == 1))
        consents_before = await db.scalar(select(func.count()).select_from(TermsConsent).where(TermsConsent.user_id == 1))
    assert histories_before == 2

    assert (await client.get("/users/me/withdrawal", headers=tony)).json()["data"]["can_withdraw"] is True
    assert await active_devices(1) == 1  # 가입 직후 로그인으로 등록된 기기
    done = await withdraw(client, tony, await withdrawal_token(client, tony))
    assert (done.status_code, done.json()) == (200, {"data": None, "message": DONE})
    assert await active_devices(1) == 0  # 등록 기기도 모두 해제
    assert {"refresh_token", "device_token"} <= {n for n, m in set_cookies(done).items() if int(m["max-age"]) == 0}

    # 개인정보는 가리고 login_id는 남긴다
    user = await user_row()
    assert user is not None and user.deleted_at is not None
    assert (user.name, user.nick_name, user.phone, user.phone_verified_at) == ("탈퇴회원", None, "", None)
    assert not user.hashed_password.startswith("$argon2")

    # 같은 아이디 재가입: 기존과 같은 409 (탈퇴했다는 사실을 드러내지 않는다)
    again = {"login_id": "ironman", "password": PASSWORD, "name": "새사람", "phone": "010-5555-6666"}
    response = await client.post("/users/signup", json=again)
    assert (error(response), response.json()["error"]["message"]) == ((409, "LOGIN_ID_ALREADY_EXISTS"), "이미 사용 중인 아이디입니다.")

    # 로그인: 없는 아이디와 같은 401 (실패도 세지 않는다)
    withdrawn, ghost = await login(client), await login(client, "nobody")
    assert (withdrawn.status_code, withdrawn.json()) == (ghost.status_code, ghost.json())
    assert error(withdrawn) == (401, "INVALID_CREDENTIALS")
    for _ in range(5):
        await login(client)
    assert error(await login(client)) == (401, "INVALID_CREDENTIALS")  # 잠금 403이 나오면 '있는 아이디'가 드러난다

    # 기존 액세스·갱신 토큰은 바로 401
    assert error(await client.get("/users/me", headers=tony)) == (401, "INVALID_TOKEN")
    refresh = await client.post("/users/token/refresh", headers=cookie_header(bank["tony"]["refresh"]))
    assert error(refresh) == (401, "INVALID_REFRESH_TOKEN")

    async with SessionLocal() as db:
        # 지운 것: AI 대화·메시지·초안, 인증번호 행(이번 탈퇴 인증과 가입 인증 포함)
        for model in (AgentConversation, AgentMessage, TransferDraft):
            assert await db.scalar(select(func.count()).select_from(model)) == 0
        assert await db.scalar(select(func.count()).select_from(VerificationCode).where(
            (VerificationCode.user_id == 1) | (VerificationCode.phone == TONY_PHONE))) == 0
        # 보존한 것: 거래내역·약관 동의 기록·계좌 행
        assert await db.scalar(select(func.count()).select_from(CheckingAccountHistory).where(
            CheckingAccountHistory.checking_account_id == 1)) == histories_before
        assert await db.scalar(select(func.count()).select_from(TermsConsent).where(TermsConsent.user_id == 1)) == consents_before > 0
        # 닫은 것: 입출금 계좌, 카드 2장, 세션
        assert (await db.get(CheckingAccount, 1)).closed_at is not None
        assert {c.status for c in await db.scalars(select(CreditCard))} == {"CLOSED"}
        assert {c.status for c in await db.scalars(select(DebitCard))} == {"CLOSED"}
        reasons = set(await db.scalars(select(RefreshToken.revoked_reason).where(RefreshToken.user_id == 1)))
        assert "WITHDRAWN" in reasons and await db.scalar(select(func.count()).select_from(RefreshToken).where(
            RefreshToken.user_id == 1, RefreshToken.revoked_at.is_(None))) == 0

    # 남이 탈퇴 회원의 계좌로 이체: 없는 계좌와 같은 404, 돈은 움직이지 않는다
    to_tony = {"from_checking_account_id": 2, "to_account_num": tony_num, "amount": 1_000}
    to_ghost = {**to_tony, "to_account_num": "110-000-000000"}
    closed, missing = await client.post("/transfers", json=to_tony, headers=bruce), await client.post("/transfers", json=to_ghost, headers=bruce)
    assert (closed.status_code, closed.json()) == (missing.status_code, missing.json())
    assert closed.json()["error"]["message"] == "받는 계좌를 찾을 수 없습니다."
    assert (await client.get("/accounts/checking/2", headers=bruce)).json()["data"]["balance"] == 100_000

    # 아이디·비밀번호 찾기: 없는 계좌와 같은 응답, 문자도 가지 않는다
    dev_inbox.clear()
    for purpose, login_id in (("FIND_LOGIN_ID", None), ("PASSWORD_RESET", "ironman")):
        shapes = []
        for num in (tony_num, "110-000-000000"):
            body = {"purpose": purpose, "account_num": num, "account_password": "1357"}
            if login_id:
                body["login_id"] = login_id
            r = await client.post("/recovery/start", json=body)
            shapes.append((r.status_code, r.json()["message"], sorted(r.json()["data"]), len(r.json()["data"]["recovery_token"])))
        assert shapes[0] == shapes[1]
    assert len(dev_inbox) == 0
