"""반복 거래 후보 탐지와 입출금 일정. 이미 분류된 Txn 목록 위의 순수 함수 (DB·I/O 없음)."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median_low

from avengers_bank.domains.money_management.analytics import add_months, effective_day, in_month, rule_matches, ym
from avengers_bank.domains.money_management.domain import Bill, Category, Direction, RecurringRule, Txn
from avengers_bank.domains.money_management.schemas import ScheduledItem

STALE_DAYS = 45
MAX_DAY_SPREAD = 5


@dataclass
class CandidateData:
    merchant_key: str
    name: str
    direction: Direction
    category: Category | None
    amount: int
    day_of_month: int
    occurrences: int
    months_observed: int
    pattern_confirmed: bool
    txns: list[Txn]  # 최신순


def detect_candidates(txns: list[Txn], rules: list[RecurringRule], today: date) -> list[CandidateData]:
    known = {(r.merchant_key, r.direction) for r in rules if r.merchant_key}  # DISMISSED/EXCLUDED 포함
    groups: dict[tuple[str, str], list[Txn]] = defaultdict(list)
    for t in txns:
        if t.merchant_key and (t.is_spending or t.is_income) and (t.merchant_key, t.direction) not in known:
            groups[(t.merchant_key, t.direction)].append(t)

    out = []
    for (key, direction), ts in groups.items():
        ts.sort(key=lambda t: t.occurred_at, reverse=True)
        latest = ts[0]
        if latest.occurred_at.date() < today - timedelta(days=STALE_DAYS):
            continue
        months = len({(t.occurred_at.year, t.occurred_at.month) for t in ts})
        amounts = [t.amount for t in ts]
        days = [t.occurred_at.day for t in ts]
        if months >= 2:
            max_ratio = 1.3 if direction == "IN" else 1.2
            # shortcut: 결제일 차이는 단순 max-min (말일↔초 경계는 놓침), 오탐이 문제되면 원형 거리로 바꾼다
            confirmed = (
                len(ts) / months <= 2
                and min(amounts) > 0
                and max(amounts) / min(amounts) <= max_ratio
                and max(days) - min(days) <= MAX_DAY_SPREAD
            )
            if not confirmed:
                continue
        elif len(ts) == 1 and latest.category == Category.SUBSCRIPTION:
            confirmed = False  # 한 번 결제로는 주기를 확정하지 않는다
        else:
            continue
        out.append(CandidateData(
            merchant_key=key,
            name=latest.merchant or key,
            direction=direction,
            category=latest.category,
            amount=latest.amount,
            day_of_month=median_low(days),
            occurrences=len(ts),
            months_observed=months,
            pattern_confirmed=confirmed,
            txns=ts,
        ))
    out.sort(key=lambda c: (not c.pattern_confirmed, -c.amount))
    return out


def schedule(
    month: date, today: date, rules: list[RecurringRule], bills: list[Bill], txns: list[Txn]
) -> list[ScheduledItem]:
    this_month = today.replace(day=1)
    next_month = add_months(month, 1)
    is_current = month == this_month

    items = [
        ScheduledItem(
            key=f"bill:{b.bill_id}",
            kind="CARD_BILL",
            name="카드대금",
            date=b.due_date,
            amount=b.total_amount,
            direction="OUT",
            status="CONFIRMED",
            account_label=b.card_label,
            bill_id=b.bill_id,
        )
        # Bill은 미납 청구서만 들어온다. 이번 달이면 연체된 이전 청구서도 보여준다
        for b in bills
        if (month <= b.due_date < next_month) or (is_current and b.due_date < month)
    ]

    if month >= this_month:  # 지난 달에는 정기 거래를 투영하지 않는다
        month_txns = [t for t in txns if in_month(t, month)]
        for r in rules:
            day = effective_day(r, month)
            if (
                r.status != "ACTIVE"
                or r.skip_month == ym(month)
                or (is_current and day < today.day)
                or any(rule_matches(r, t) for t in month_txns)
            ):
                continue
            items.append(ScheduledItem(
                key=f"recurring:{r.recurring_id}",
                kind="RECURRING",
                name=r.name,
                date=month.replace(day=day),
                amount=r.amount,
                direction=r.direction,
                status="ESTIMATED",
                account_label=None,
                recurring_id=r.recurring_id,
            ))

    items.sort(key=lambda i: (i.date, i.key))
    return items
