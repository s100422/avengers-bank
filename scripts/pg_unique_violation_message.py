"""계좌·카드번호 중복 오류 메시지 확인 (C-020, C-023).

서비스는 `IntegrityError` 메시지에 "account_num" / "card_num"이 있으면 번호 충돌로 보고 새 번호로 다시 시도한다.
이 가정이 실제 PostgreSQL에서 맞는지(그리고 번호 충돌이 아닌 오류가 잘못 걸리지 않는지) 확인한다.

실행: uv run python scripts/pg_unique_violation_message.py
"""

from sqlalchemy.exc import IntegrityError

from _common import check, cleanup, connect, execute, finish, make_checking, make_user, product_id

LOGIN = "verify_unique"


def attempt(stmt, **params):
    """실행해 보고 IntegrityError 메시지(없으면 None)를 돌려준다."""
    try:
        execute(stmt, **params)
    except IntegrityError as e:
        return str(e.orig)
    return None


def main():
    connect()
    user_id = make_user(LOGIN)
    checking_id = make_checking(user_id, "110-777-400001")
    account_product = product_id("account_products", "CHECKING")
    credit_product, debit_product = product_id("card_products", "CREDIT"), product_id("card_products", "DEBIT")
    p = {"u": user_id, "a": checking_id, "ap": account_product, "cp": credit_product, "dp": debit_product}

    # (표, 번호 컬럼, 한 줄을 넣는 SQL). 번호는 :n
    cases = [
        ("checking_accounts", "account_num",
         "insert into checking_accounts(user_id, product_id, account_num, balance, per_transfer_limit, daily_transfer_limit)"
         " values (:u, :ap, :n, 0, 1, 1)", "110-777-400002"),
        ("deposit_accounts", "account_num",
         "insert into deposit_accounts(user_id, product_id, account_num, balance, maturity_date, status)"
         " values (:u, :ap, :n, 0, date '2030-01-01', 'ACTIVE')", "120-777-400001"),
        ("savings_accounts", "account_num",
         "insert into savings_accounts(user_id, product_id, account_num, balance, monthly_payment, monthly_deposit_date, maturity_date, status)"
         " values (:u, :ap, :n, 0, 1, 1, date '2030-01-01', 'ACTIVE')", "220-777-400001"),
        ("credit_cards", "card_num",
         "insert into credit_cards(user_id, product_id, checking_account_id, card_num, credit_limit, outstanding_amount, payment_date, status)"
         " values (:u, :cp, :a, :n, 1000000, 0, 14, 'ACTIVE')", "4000-9999-9999-9001"),
        ("debit_cards", "card_num",
         "insert into debit_cards(user_id, product_id, checking_account_id, card_num, accumulated_amount, status)"
         " values (:u, :dp, :a, :n, 0, 'ACTIVE')", "5000-9999-9999-9001"),
    ]

    passed = True
    try:
        print("[번호가 겹칠 때] 같은 번호를 두 번 넣으면 메시지에 번호 컬럼 이름이 있어야 한다")
        for table, column, stmt, number in cases:
            execute(stmt, n=number, **p)
            message = attempt(stmt, n=number, **p)
            first_line = (message or "(오류 없음!)").splitlines()[0]
            passed &= check(f"{table}: '{column}' 포함 → {first_line}", message is not None and column in message)

        print("[번호 충돌이 아닐 때] 없는 사용자·계좌를 가리키는 외래키 오류에는 번호 컬럼 이름이 없어야 한다 (헛재시도 방지)")
        bad = {"u": -1, "a": -1, "ap": account_product, "cp": credit_product, "dp": debit_product}
        fresh_numbers = {"checking_accounts": "110-777-400099", "credit_cards": "4000-9999-9999-9099"}  # 겹치지 않는 번호
        for table, column, stmt, _ in cases:
            if table in fresh_numbers:
                message = attempt(stmt, n=fresh_numbers[table], **bad)  # 새 번호 + 잘못된 외래키
                first_line = (message or "(오류 없음!)").splitlines()[0]
                passed &= check(f"{table}: '{column}' 없음 → {first_line}", message is not None and column not in message)
    finally:
        cleanup(LOGIN)
        print("정리 완료")
    finish(passed, f"검증 결과: {'통과' if passed else '실패'}")


if __name__ == "__main__":
    main()
