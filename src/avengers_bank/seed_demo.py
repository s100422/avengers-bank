"""데모 사용자와 계좌를 실행 중인 API로 만든다: uv run python -m avengers_bank.seed_demo [login_id] [password]

서버(fastapi dev)가 떠 있고, 상품 시드·약관 발행이 끝나 있어야 한다. ENABLE_DEV_ENDPOINTS=true 필요(잔액 충전).
사용자가 없으면 가입하고, 있으면 로그인한다. 실행할 때마다 계좌가 새로 추가된다.
만드는 계좌: 생활비 통장(최종 잔액 13,000,000원), 월급 통장(2,000,000원), 정기예금(가입 금액 3,000,000원을
생활비 통장에서 출금해 개설), 정기적금(잔액 0원).
"""

import sys
from datetime import date, timedelta

import httpx

BASE = "http://127.0.0.1:8000"
LOGIN_ID = sys.argv[1] if len(sys.argv) > 1 else "admin123"
PASSWORD = sys.argv[2] if len(sys.argv) > 2 else "password1234"


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


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=10) as c:
        r = c.post("/users/signup", json={
            "login_id": LOGIN_ID, "password": PASSWORD, "name": "토니 스타크", "nick_name": None, "phone": "010-1234-5678",
        })
        if r.status_code not in (201, 409):
            sys.exit(f"signup -> {r.status_code} {r.text}")
        token = call(c, "POST", "/users/login", json={"login_id": LOGIN_ID, "password": PASSWORD})["access_token"]
        c.headers["Authorization"] = f"Bearer {token}"

        by_name = {p["name"]: p["product_id"] for p in call(c, "GET", "/products/accounts")}
        future = (date.today() + timedelta(days=365)).isoformat()
        far = (date.today() + timedelta(days=365 * 2)).isoformat()

        def open_(kind: str, product: str, body: dict) -> dict:
            pid = by_name[product]
            return call(c, "POST", f"/accounts/{kind}", json={"product_id": pid, "terms": consent(c, kind, pid), **body})

        main_acc = open_("checking", "어벤져스 입출금통장", {"nickname": "생활비 통장"})
        # 예금 가입 금액이 생활비 통장에서 빠지므로 그만큼 더 충전해야 최종 잔액이 정확히 1,300만 원이 된다.
        deposit_amount = 3_000_000
        call(c, "POST", f"/dev/accounts/checking/{main_acc['account_id']}/charge", json={"amount": 13_000_000 + deposit_amount})
        salary = open_("checking", "어벤져스 월급통장", {"nickname": "월급 통장"})
        call(c, "POST", f"/dev/accounts/checking/{salary['account_id']}/charge", json={"amount": 2_000_000})
        open_("deposit", "어벤져스 정기예금", {
            "nickname": "목돈 예금", "maturity_date": future,
            "initial_amount": deposit_amount, "from_checking_account_id": main_acc["account_id"],
        })
        open_("savings", "어벤져스 정기적금", {"nickname": "여행 적금", "monthly_payment": 300_000, "monthly_deposit_date": 25, "maturity_date": far})

        for a in call(c, "GET", "/accounts"):
            print(f"{a['account_type']:9} {a['account_num']}  {a['balance']:>12,}원  {a.get('nickname')}")


if __name__ == "__main__":
    main()
