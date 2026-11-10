"""analytics 순수 함수 테스트 (DB 없음)."""

from datetime import date, datetime
from itertools import count

from avengers_bank.domains.money_management.analytics import category_detail, compute
from avengers_bank.domains.money_management.domain import Category, RecurringRule, Txn

_ids = count(1)
NOV = date(2026, 11, 1)
TODAY = date(2026, 11, 15)


def txn(day: str, amount: int, merchant: str = "가게", category=Category.DINING, **kw) -> Txn:
    kw.setdefault("source", "credit")
    kw.setdefault("direction", "OUT")
    return Txn(
        source_id=next(_ids), occurred_at=datetime.fromisoformat(day + "T12:00:00"), amount=amount,
        merchant=merchant, merchant_key=merchant.lower(), checking_type=kw.pop("checking_type", None),
        payment_label="카드", category=category, **kw,
    )


def rule(rid: int, merchant: str, amount: int, day: int, status="ACTIVE", direction="OUT", skip=None) -> RecurringRule:
    return RecurringRule(
        recurring_id=rid, name=merchant, merchant_key=merchant.lower(), direction=direction,
        category=Category.SUBSCRIPTION, amount=amount, day_of_month=day, status=status, skip_month=skip,
    )


def test_no_baseline_uses_this_month_and_never_invents_average():
    f, p, cats, items = compute(NOV, TODAY, [txn("2026-11-03", 30000), txn("2026-11-05", 10000, category=Category.CAFE)], [])
    assert f.baseline.months == 0 and f.baseline.monthly_avg is None and f.change_rate is None
    assert p.status == "UNKNOWN" and p.diff_rate is None and p.baseline_cumulative is None
    assert f.variable_basis == "THIS_MONTH"
    assert f.remaining_variable == round(40000 / 15 * 15)
    assert [c.category for c in cats] == [Category.DINING, Category.CAFE]  # 사용액 큰 순
    assert all(c.status == "UNKNOWN" and c.diff is None and c.projected is None for c in cats)


def test_baseline_cutoff_at_earliest_data():
    one = compute(NOV, TODAY, [txn("2026-10-10", 1000), txn("2026-11-01", 1000)], [])[0].baseline
    assert (one.months, one.period_start, one.period_end) == (1, date(2026, 10, 1), date(2026, 10, 31))
    two = compute(NOV, TODAY, [txn("2026-09-20", 1000), txn("2026-11-01", 1000)], [])[0].baseline
    assert two.months == 2 and two.period_start == date(2026, 9, 1)
    assert two.monthly_avg == 500  # 10월은 데이터 기간 안의 0원 달


def test_three_month_baseline_one_off_and_card_bill():
    txns = [
        txn("2026-07-10", 999999),  # 3개월 밖
        txn("2026-08-10", 30000), txn("2026-09-10", 30000), txn("2026-10-10", 30000),
        txn("2026-10-12", 90000, is_one_off=True),  # 기준에서 제외
        txn("2026-11-05", 20000),
        txn("2026-11-06", 100000, is_one_off=True),  # 실제에는 포함
        txn("2026-11-07", 500000, source="checking", checking_type="CARD_BILL_PAYMENT", category=None),
    ]
    f, p, cats, _ = compute(NOV, TODAY, txns, [])
    assert f.baseline.months == 3 and f.baseline.monthly_avg == 30000
    assert f.actual_to_date == 120000  # 카드대금 출금은 소비가 아님
    rate = (30000 / 31 + 30000 / 30 + 30000 / 31) / 3
    assert f.variable_basis == "BASELINE" and f.remaining_variable == round(rate * 15)
    assert f.projected_total == 120000 + f.remaining_variable
    assert f.change_rate == (f.projected_total - 30000) / 30000
    assert p.status == "HIGHER" and p.diff_rate == (120000 - 30000) / 30000
    assert len(p.actual_cumulative) == 15 and len(p.projected_cumulative) == 15
    assert p.projected_cumulative[-1] == f.projected_total
    assert p.baseline_cumulative[8] == 0 and p.baseline_cumulative[9] == 30000


def test_recurring_paid_skipped_excluded():
    rules = [
        rule(1, "Netflix", 17000, 20),  # 아직 안 나감 → 남은 정기 지출
        rule(2, "Phone", 60000, 25),  # 이번 달 이미 나감
        rule(3, "Gym", 50000, 28, skip="2026-11"),
        rule(4, "Rent", 500000, 27, status="EXCLUDED"),
        rule(5, "Salary", 3000000, 25, direction="IN"),
        rule(6, "Insurance", 31000, 31),  # 11월은 30일까지 → 30일
    ]
    txns = [
        txn("2026-10-20", 17000, "Netflix"), txn("2026-10-25", 60000, "Phone"),
        txn("2026-10-27", 500000, "Rent"), txn("2026-10-05", 31000),
        txn("2026-11-03", 60000, "Phone"),
    ]
    f, p, _, items = compute(NOV, TODAY, txns, rules)
    assert f.remaining_recurring == 17000 + 31000
    assert [(i.key, i.date) for i in items] == [("recurring:1", date(2026, 11, 20)), ("recurring:6", date(2026, 11, 30))]
    assert items[0].status == "ESTIMATED" and items[0].direction == "OUT" and items[0].account_label is None
    # 정기 거래(제외 포함)에 연결된 거래는 변동지출에서 빠진다: 10월 변동 = 31000뿐
    assert f.remaining_variable == round(31000 / 31 * 15)
    assert p.projected_cumulative[-1] == f.projected_total
    assert p.projected_cumulative[4] - p.projected_cumulative[3] > 17000  # 20일에 정기 지출 반영


def test_past_month():
    txns = [txn("2026-09-10", 30000), txn("2026-10-10", 40000), txn("2026-10-30", 5000)]
    f, p, cats, items = compute(date(2026, 10, 1), TODAY, txns, [rule(1, "Netflix", 17000, 31)])
    assert not f.is_current_month
    assert (f.remaining_recurring, f.remaining_variable, f.projected_total) == (0, 0, 45000)
    assert p.today_day == 31 and p.projected_cumulative == [] and items == []
    assert cats[0].projected == cats[0].actual == 45000


def test_category_status_thresholds_and_sort():
    txns = [
        txn("2026-10-01", 10000), txn("2026-10-01", 100000, category=Category.CAFE),
        txn("2026-10-01", 50000, category=Category.MART), txn("2026-10-20", 30000, category=Category.ONLINE),
        txn("2026-11-02", 14000), txn("2026-11-02", 115000, category=Category.CAFE),
    ]
    cats = {c.category: c for c in compute(NOV, TODAY, txns, [])[2]}
    order = [c.category for c in compute(NOV, TODAY, txns, [])[2]]
    assert order == [Category.MART, Category.CAFE, Category.DINING, Category.ONLINE]
    assert cats[Category.DINING].status == "NORMAL"  # +4000 < 5000
    assert cats[Category.CAFE].status == "HIGHER"  # +15000 > max(5000, 10000)
    assert cats[Category.MART].status == "LOWER" and cats[Category.MART].actual == 0
    assert cats[Category.ONLINE].baseline_to_date == 0 and cats[Category.ONLINE].projected == 30000
    assert cats[Category.CAFE].label == "카페"


def test_category_detail():
    txns = [
        txn("2026-09-03", 8000, "Starbucks", Category.CAFE),
        txn("2026-10-03", 12000, "Starbucks", Category.CAFE),
        txn("2026-10-04", 50000, "Mega", Category.CAFE, is_one_off=True),
        txn("2026-11-01", 4000, "스타벅스 강남", Category.CAFE, ),
        txn("2026-11-02", 3000, "Mega", Category.CAFE),
        txn("2026-11-03", 6000, "스타벅스 역삼", Category.CAFE),
        txn("2026-11-03", 99000, "Food", Category.DINING),
    ]
    txns[3].merchant_key = txns[5].merchant_key = "starbucks"
    spend, base, monthly, merchants = category_detail(NOV, TODAY, txns, Category.CAFE)
    assert spend.actual == 13000
    assert base.months == 2 and base.monthly_avg == 10000  # 일회성 제외
    assert [(m.month, m.amount) for m in monthly] == [("2026-09", 8000), ("2026-10", 62000), ("2026-11", 13000)]
    assert [(m.merchant, m.amount, m.count) for m in merchants] == [("스타벅스 역삼", 10000, 2), ("Mega", 3000, 1)]
    empty = category_detail(NOV, TODAY, txns, Category.MEDICAL)[0]
    assert empty.actual == 0 and empty.status == "NORMAL"
