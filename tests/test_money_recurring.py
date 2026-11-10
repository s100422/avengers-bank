"""recurring 순수 함수 테스트 (DB 없음)."""

from datetime import date, datetime
from itertools import count

from avengers_bank.domains.money_management.domain import Bill, Category, RecurringRule, Txn
from avengers_bank.domains.money_management.recurring import detect_candidates, schedule

_ids = count(1)
TODAY = date(2026, 11, 11)
NOV = date(2026, 11, 1)


def txn(day: str, amount: int, merchant: str, category=Category.SUBSCRIPTION, **kw) -> Txn:
    kw.setdefault("source", "credit")
    kw.setdefault("direction", "OUT")
    return Txn(
        source_id=next(_ids), occurred_at=datetime.fromisoformat(day + "T09:00:00"), amount=amount,
        merchant=merchant, merchant_key=merchant.lower(), checking_type=kw.pop("checking_type", None),
        payment_label="카드", category=category, **kw,
    )


def rule(rid: int, merchant: str, amount: int, day: int, status="ACTIVE", direction="OUT", skip=None) -> RecurringRule:
    return RecurringRule(
        recurring_id=rid, name=merchant, merchant_key=merchant.lower(), direction=direction,
        category=None, amount=amount, day_of_month=day, status=status, skip_month=skip,
    )


def test_detect_candidates():
    txns = [
        txn("2026-09-05", 17000, "Netflix"), txn("2026-10-06", 17000, "Netflix"), txn("2026-11-05", 17000, "Netflix"),
        txn("2026-11-01", 9900, "Youtube"),  # 구독 1회 → 미확정 후보
        txn("2026-11-02", 30000, "Sushi", Category.DINING),  # 구독 아닌 1회 → 후보 아님
        txn("2026-10-03", 5000, "Melon"), txn("2026-11-03", 5000, "Melon"),  # 무시한 후보
        txn("2026-10-01", 10000, "Gym"), txn("2026-11-01", 13000, "Gym"),  # 금액 차이 1.3배
        txn("2026-10-01", 7000, "Cloud"), txn("2026-11-20", 7000, "Cloud"),  # 결제일 차이 19일
        txn("2026-08-01", 4000, "Old"), txn("2026-09-01", 4000, "Old"),  # 45일 넘게 지남
        txn("2026-10-10", 100000, "Me", None, source="checking", checking_type="TRANSFER_OUT", is_self_transfer=True),
        txn("2026-11-10", 100000, "Me", None, source="checking", checking_type="TRANSFER_OUT", is_self_transfer=True),
        txn("2026-09-25", 2500000, "Company", None, source="checking", checking_type="TRANSFER_IN", direction="IN"),
        txn("2026-10-25", 3000000, "Company", None, source="checking", checking_type="TRANSFER_IN", direction="IN"),
    ]
    found = detect_candidates(txns, [rule(1, "Melon", 5000, 3, status="DISMISSED")], TODAY)
    assert [(c.merchant_key, c.pattern_confirmed) for c in found] == [
        ("company", True), ("netflix", True), ("youtube", False),
    ]
    company, netflix, youtube = found
    assert company.direction == "IN" and company.amount == 3000000  # 수입은 1.3배까지 허용
    assert (netflix.day_of_month, netflix.occurrences, netflix.months_observed) == (5, 3, 3)
    assert [t.occurred_at.month for t in netflix.txns] == [11, 10, 9]
    assert youtube.occurrences == 1 and youtube.category == Category.SUBSCRIPTION


def test_schedule_current_month():
    bills = [
        Bill(bill_id=1, due_date=date(2026, 11, 25), total_amount=400000, card_label="신용카드 ****1234"),
        Bill(bill_id=2, due_date=date(2026, 10, 25), total_amount=100000, card_label="신용카드 ****1234"),  # 연체
        Bill(bill_id=3, due_date=date(2026, 12, 25), total_amount=200000, card_label="신용카드 ****1234"),
    ]
    rules = [
        rule(1, "Netflix", 17000, 20),
        rule(2, "Salary", 3000000, 25, direction="IN"),
        rule(3, "Phone", 60000, 5),  # 오늘 이전
        rule(4, "Gym", 50000, 15),  # 이미 나감
        rule(5, "Rent", 500000, 27, skip="2026-11"),
        rule(6, "Melon", 5000, 12, status="EXCLUDED"),
        rule(7, "Today", 1000, 11),  # 오늘 → 포함
    ]
    items = schedule(NOV, TODAY, rules, bills, [txn("2026-11-03", 50000, "Gym")])
    assert [(i.key, i.date) for i in items] == [
        ("bill:2", date(2026, 10, 25)), ("recurring:7", date(2026, 11, 11)), ("recurring:1", date(2026, 11, 20)),
        ("bill:1", date(2026, 11, 25)), ("recurring:2", date(2026, 11, 25)),
    ]
    bill = items[0]
    assert (bill.kind, bill.status, bill.name, bill.account_label, bill.bill_id) == (
        "CARD_BILL", "CONFIRMED", "카드대금", "신용카드 ****1234", 2,
    )
    assert items[4].direction == "IN" and items[4].status == "ESTIMATED" and items[4].recurring_id == 2


def test_schedule_past_month_only_bills_due_then():
    bills = [
        Bill(bill_id=1, due_date=date(2026, 10, 25), total_amount=100000, card_label="카드"),
        Bill(bill_id=2, due_date=date(2026, 9, 25), total_amount=100000, card_label="카드"),
    ]
    items = schedule(date(2026, 10, 1), TODAY, [rule(1, "Netflix", 17000, 20)], bills, [])
    assert [i.key for i in items] == ["bill:1"]
