"""이번 달 소비 집계·예측. 이미 분류된 Txn 목록 위의 순수 함수 (DB·I/O 없음).

txns에는 선택한 달과 그 이전 최대 3개월이 들어온다. 소비가 아닌 거래도 섞여 있으니 is_spending으로 거른다.
"""

import calendar
from collections import defaultdict
from datetime import date
from itertools import accumulate

from avengers_bank.domains.money_management.domain import LABELS, Category, RecurringRule, Txn
from avengers_bank.domains.money_management.schemas import (
    Baseline,
    CategorySpend,
    Forecast,
    MerchantSpend,
    MonthAmount,
    Pace,
    ScheduledItem,
)

PACE_THRESHOLD = 0.05


def days_in(m: date) -> int:
    return calendar.monthrange(m.year, m.month)[1]


def ym(m: date) -> str:
    return f"{m.year:04d}-{m.month:02d}"


def add_months(m: date, k: int) -> date:
    i = m.year * 12 + m.month - 1 + k
    return date(i // 12, i % 12 + 1, 1)


def in_month(t: Txn, m: date) -> bool:
    return t.occurred_at.year == m.year and t.occurred_at.month == m.month


def effective_day(rule: RecurringRule, m: date) -> int:
    return min(rule.day_of_month, days_in(m))


def rule_matches(rule: RecurringRule, t: Txn) -> bool:
    return rule.merchant_key is not None and t.merchant_key == rule.merchant_key and t.direction == rule.direction


def _today_day(month: date, today: date) -> int:
    return today.day if (month.year, month.month) == (today.year, today.month) else days_in(month)


def _baseline_months(month: date, txns: list[Txn]) -> list[date]:
    """선택한 달 바로 전 최대 3개 완결 월 (오래된 순). 가장 이른 거래가 있는 달보다 앞으로는 가지 않는다."""
    if not txns:
        return []
    first = min(t.occurred_at for t in txns).date().replace(day=1)
    return [m for m in (add_months(month, -k) for k in (3, 2, 1)) if m >= first]


def _baseline(months: list[date], monthly_avg: int | None) -> Baseline:
    if not months:
        return Baseline(months=0, period_start=None, period_end=None, monthly_avg=None)
    last = months[-1]
    return Baseline(
        months=len(months),
        period_start=months[0],
        period_end=last.replace(day=days_in(last)),
        monthly_avg=monthly_avg,
    )


def _daily(txns: list[Txn], m: date, upto: int | None = None) -> list[int]:
    """m월 일자별 합계 (길이 = 그 달 일수). upto가 있으면 그 일자 이후는 0."""
    days = [0] * days_in(m)
    for t in txns:
        if in_month(t, m) and (upto is None or t.occurred_at.day <= upto):
            days[t.occurred_at.day - 1] += t.amount
    return days


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _cum_mean(baseline_txns: list[Txn], months: list[date], day: int) -> float:
    """기준 각 달의 day일까지 누적 소비 평균. 기준 달이 day보다 짧으면 그 달 전체 합계."""
    cums = []
    for m in months:
        daily = _daily(baseline_txns, m)
        cums.append(sum(daily[: min(day, len(daily))]))
    return _mean(cums)


def _category_spend(
    category: Category,
    month: date,
    today_day: int,
    is_current: bool,
    spend: list[Txn],
    months: list[date],
) -> CategorySpend:
    cat_txns = [t for t in spend if (t.category or Category.UNCLASSIFIED) == category]
    actual = sum(t.amount for t in cat_txns if in_month(t, month) and t.occurred_at.day <= today_day)
    if not months:
        return CategorySpend(
            category=category, label=LABELS[category], actual=actual,
            baseline_to_date=None, diff=None, projected=None, status="UNKNOWN",
        )
    base_txns = [t for t in cat_txns if not t.is_one_off]
    to_date = round(_cum_mean(base_txns, months, today_day))
    full = round(_mean([sum(_daily(base_txns, m)) for m in months]))
    diff = actual - to_date
    threshold = max(5000, 0.1 * to_date)
    status = "HIGHER" if diff > threshold else "LOWER" if diff < -threshold else "NORMAL"
    projected = actual + max(0, full - to_date) if is_current else actual
    return CategorySpend(
        category=category, label=LABELS[category], actual=actual,
        baseline_to_date=to_date, diff=diff, projected=projected, status=status,
    )


def compute(
    month: date, today: date, txns: list[Txn], rules: list[RecurringRule]
) -> tuple[Forecast, Pace, list[CategorySpend], list[ScheduledItem]]:
    dim = days_in(month)
    today_day = _today_day(month, today)
    is_current = (month.year, month.month) == (today.year, today.month)
    remaining_days = dim - today_day

    spend = [t for t in txns if t.is_spending]
    months = _baseline_months(month, txns)
    base_spend = [t for t in spend if not t.is_one_off]

    # 실제 소비: 일회성 포함
    actual_cum = list(accumulate(_daily(spend, month, today_day)[:today_day]))
    actual = actual_cum[-1]

    monthly_avg = round(_mean([sum(_daily(base_spend, m)) for m in months])) if months else None
    baseline_cum = [round(_cum_mean(base_spend, months, d)) for d in range(1, dim + 1)] if months else None

    # 정기 거래(ACTIVE/EXCLUDED)에 연결된 거래는 변동지출에서 뺀다
    linked = [r for r in rules if r.status in ("ACTIVE", "EXCLUDED")]
    variable = [t for t in base_spend if not any(rule_matches(r, t) for r in linked)]

    # 남은 정기 지출: 이번 달 아직 안 나간 ACTIVE 출금만
    month_txns = [t for t in txns if in_month(t, month) and t.occurred_at.day <= today_day]
    remaining_rules = sorted(
        (
            r for r in rules
            if r.status == "ACTIVE" and r.direction == "OUT" and r.skip_month != ym(month)
            and effective_day(r, month) > today_day
            and not any(rule_matches(r, t) for t in month_txns)
        ),
        key=lambda r: (effective_day(r, month), r.recurring_id),
    )
    remaining_recurring = sum(r.amount for r in remaining_rules)

    if not is_current:
        rate, basis = 0.0, "NONE"  # 지난 달은 추정하지 않는다
    elif months:
        rate, basis = _mean([sum(_daily(variable, m)) / days_in(m) for m in months]), "BASELINE"
    elif (this_var := sum(_daily(variable, month, today_day))) > 0:
        rate, basis = this_var / today_day, "THIS_MONTH"
    else:
        rate, basis = 0.0, "NONE"
    remaining_variable = round(rate * remaining_days)
    projected_total = actual + remaining_recurring + remaining_variable

    # 누적 예상: round(rate*i)라서 마지막 값이 projected_total과 정확히 같다
    projected_cum = []
    for i in range(1, remaining_days + 1):
        day = today_day + i
        rec = sum(r.amount for r in remaining_rules if effective_day(r, month) <= day)
        projected_cum.append(actual + round(rate * i) + rec)

    forecast = Forecast(
        is_current_month=is_current,
        actual_to_date=actual,
        remaining_recurring=remaining_recurring,
        remaining_variable=remaining_variable,
        projected_total=projected_total,
        variable_basis=basis,
        baseline=_baseline(months, monthly_avg),
        change_rate=(projected_total - monthly_avg) / monthly_avg if monthly_avg else None,
    )

    base_today = baseline_cum[today_day - 1] if baseline_cum else 0
    diff_rate = (actual - base_today) / base_today if base_today else None
    if diff_rate is None:
        status = "UNKNOWN"
    else:
        status = "HIGHER" if diff_rate > PACE_THRESHOLD else "LOWER" if diff_rate < -PACE_THRESHOLD else "NORMAL"
    pace = Pace(
        status=status,
        diff_rate=diff_rate,
        today_day=today_day,
        days_in_month=dim,
        actual_cumulative=actual_cum,
        projected_cumulative=projected_cum,
        baseline_cumulative=baseline_cum,
    )

    in_baseline = {t.category or Category.UNCLASSIFIED for t in base_spend if any(in_month(t, m) for m in months)}
    cats = [_category_spend(c, month, today_day, is_current, spend, months) for c in Category]
    cats = [c for c in cats if c.actual > 0 or c.category in in_baseline]
    if months:
        cats.sort(key=lambda c: (-abs(c.diff), -c.actual))
    else:
        cats.sort(key=lambda c: -c.actual)

    items = [
        ScheduledItem(
            key=f"recurring:{r.recurring_id}",
            kind="RECURRING",
            name=r.name,
            date=month.replace(day=effective_day(r, month)),
            amount=r.amount,
            direction="OUT",
            status="ESTIMATED",
            account_label=None,
            recurring_id=r.recurring_id,
        )
        for r in remaining_rules
    ]
    return forecast, pace, cats, items


def category_detail(
    month: date, today: date, txns: list[Txn], category: Category
) -> tuple[CategorySpend, Baseline, list[MonthAmount], list[MerchantSpend]]:
    today_day = _today_day(month, today)
    is_current = (month.year, month.month) == (today.year, today.month)
    spend = [t for t in txns if t.is_spending]
    months = _baseline_months(month, txns)

    cat_spend = _category_spend(category, month, today_day, is_current, spend, months)
    cat_txns = [t for t in spend if (t.category or Category.UNCLASSIFIED) == category]
    # 상세 화면의 기준은 이 항목의 월평균 (일회성 제외)
    base_cat = [t for t in cat_txns if not t.is_one_off]
    monthly_avg = round(_mean([sum(_daily(base_cat, m)) for m in months])) if months else None

    # 월별 실제 합계: 일회성 포함
    monthly = [MonthAmount(month=ym(m), amount=sum(_daily(cat_txns, m))) for m in months]
    monthly.append(MonthAmount(month=ym(month), amount=sum(_daily(cat_txns, month, today_day))))

    groups: dict[str, list[Txn]] = defaultdict(list)
    for t in cat_txns:
        if in_month(t, month) and t.occurred_at.day <= today_day:
            groups[t.merchant_key or t.merchant or ""].append(t)
    merchants = []
    for key, ts in groups.items():
        latest = max(ts, key=lambda t: t.occurred_at)
        merchants.append(MerchantSpend(merchant=latest.merchant or key or "알 수 없음", amount=sum(t.amount for t in ts), count=len(ts)))
    merchants.sort(key=lambda s: -s.amount)

    return cat_spend, _baseline(months, monthly_avg), monthly, merchants
