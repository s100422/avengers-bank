"""데모 사용자와 계좌를 실행 중인 API로 만든다: uv run python -m avengers_bank.seed_demo [login_id] [password]

기본값은 admin123 / Passw0rd!23. 직접 줄 때는 가입 규칙을 지켜야 한다: 아이디는 영문 소문자·숫자·_ 4~20자,
비밀번호는 8~128자에 영문·숫자·특수문자를 각각 1자 이상(아이디와 같으면 안 됨). 셸에서 '!'는 따옴표로 감싼다.
예전 규칙(예: password1234)으로 이미 가입된 데모 계정은 로그인 규칙이 그대로라 그 비밀번호를 넘기면 계속 로그인된다.

서버(fastapi dev)가 떠 있고, 상품 시드·약관 발행이 끝나 있어야 한다. ENABLE_DEV_ENDPOINTS=true 필요(잔액 충전, 가입 때
휴대폰 인증번호를 개발용 문자함 GET /dev/sms에서 읽는다). 사용자가 없으면 가입하고, 있으면 로그인한다.
(로그인을 먼저 시도하므로 비밀번호를 틀리게 주면 로그인 실패로 세어진다. 5번이면 잠긴다 → admin unlock) 실행할 때마다 계좌가 새로 추가된다.
만드는 계좌: 생활비 통장(최종 잔액 13,000,000원), 월급 통장(2,000,000원), 정기예금(가입 금액 3,000,000원을
생활비 통장에서 출금해 개설), 정기적금(잔액 0원).
"""

import re
import sys
from datetime import date, timedelta

import httpx

BASE = "http://127.0.0.1:8000"
LOGIN_ID = sys.argv[1] if len(sys.argv) > 1 else "admin123"
PASSWORD = sys.argv[2] if len(sys.argv) > 2 else "Passw0rd!23"
ACCOUNT_PASSWORD = "1357"  # 데모 계좌 3종의 계좌 비밀번호 (숫자 4자리)
PHONE = "010-1234-5678"


def call(c: httpx.Client, method: str, path: str, **kw):
    r = c.request(method, path, **kw)
    if r.status_code >= 400:
        sys.exit(f"{method} {path} -> {r.status_code} {r.text}")
    return r.json()["data"]


def consent(c: httpx.Client, kind: str, product_id: int) -> dict:
    t = call(c, "GET", f"/terms/products/{kind}/{product_id}")
    return {
        "revision_id": t["revision_id"], "set_hash": t["set_hash"],
        "agreements": [{"terms_version_id": i["terms_version_id"], "agreed": True} for i in t["items"]],
    }


def signup(c: httpx.Client) -> None:
    """인증번호 발송 → GET /dev/sms(개발용 문자함)에서 코드 읽기 → 확인 → 가입 (C-090)."""
    sent = call(c, "POST", "/verification/phone/send", json={"phone": PHONE, "purpose": "SIGNUP_PHONE"})
    text = call(c, "GET", "/dev/sms", params={"phone": PHONE})[0]["text"]
    code = re.search(r"\d{6}", text).group()
    token = call(c, "POST", "/verification/phone/verify", json={"verification_id": sent["verification_id"], "code": code})
    call(c, "POST", "/users/signup", json={
        "login_id": LOGIN_ID, "password": PASSWORD, "name": "토니 스타크", "nick_name": None, "phone": PHONE,
        "phone_verification_token": token["verification_token"],
    })


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=10) as c:
        login = {"login_id": LOGIN_ID, "password": PASSWORD}
        r = c.post("/users/login", json=login)
        if r.status_code == 401:  # 아직 없는 사용자: 휴대폰 인증(개발용 문자함) → 가입
            signup(c)
            r = c.post("/users/login", json=login)
        if r.status_code != 200:
            sys.exit(f"login -> {r.status_code} {r.text}")
        token = r.json()["data"]["access_token"]
        c.headers["Authorization"] = f"Bearer {token}"

        by_name = {p["name"]: p["product_id"] for p in call(c, "GET", "/products/accounts")}
        future = (date.today() + timedelta(days=365)).isoformat()
        far = (date.today() + timedelta(days=365 * 2)).isoformat()

        def open_(kind: str, product: str, body: dict) -> dict:
            pid = by_name[product]
            return call(c, "POST", f"/accounts/{kind}", json={
                "product_id": pid, "terms": consent(c, kind, pid), "account_password": ACCOUNT_PASSWORD, **body,
            })

        main_acc = open_("checking", "어벤져스 입출금통장", {"nickname": "생활비 통장"})
        # 예금 가입 금액이 생활비 통장에서 빠지므로 그만큼 더 충전해야 최종 잔액이 정확히 1,300만 원이 된다.
        deposit_amount = 3_000_000
        call(c, "POST", f"/dev/accounts/checking/{main_acc['account_id']}/charge", json={"amount": 13_000_000 + deposit_amount})
        salary = open_("checking", "어벤져스 월급통장", {"nickname": "월급 통장"})
        call(c, "POST", f"/dev/accounts/checking/{salary['account_id']}/charge", json={"amount": 2_000_000})
        open_("deposit", "어벤져스 정기예금", {
            "nickname": "목돈 예금", "maturity_date": future,
            "initial_amount": deposit_amount, "from_checking_account_id": main_acc["account_id"],
            "from_account_password": ACCOUNT_PASSWORD,
        })
        open_("savings", "어벤져스 정기적금", {"nickname": "여행 적금", "monthly_payment": 300_000, "monthly_deposit_date": 25, "maturity_date": far})

        for a in call(c, "GET", "/accounts"):
            print(f"{a['account_type']:9} {a['account_num']}  {a['balance']:>12,}원  {a.get('nickname')}")


if __name__ == "__main__":
    main()
