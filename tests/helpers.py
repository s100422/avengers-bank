"""테스트용 예금 개설 도우미. 예금은 가입 때 입출금 계좌에서 initial_amount를 옮겨 와야만 열린다."""

from datetime import timedelta

from avengers_bank.core.timezone import today_kst

FUTURE = (today_kst() + timedelta(days=365)).isoformat()


async def open_deposit(client, headers, amount=1000, from_id=None, **extra):
    """예금 개설 응답을 돌려준다. from_id가 없으면 새 입출금 계좌를 만들어 amount만큼 충전한 뒤 거기서 낸다."""
    if from_id is None:
        from_id = (await client.post("/accounts/checking", json={"product_id": 1}, headers=headers)).json()["data"]["account_id"]
        await client.post(f"/dev/accounts/checking/{from_id}/charge", json={"amount": amount}, headers=headers)
    body = {"product_id": 2, "maturity_date": FUTURE, "initial_amount": amount, "from_checking_account_id": from_id, **extra}
    return await client.post("/accounts/deposit", json=body, headers=headers)
