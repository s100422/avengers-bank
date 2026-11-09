"""예금·적금 해지 이자 계산 (C-043). 단리, 입금 한 건씩 일할 계산한다."""

import calendar
from datetime import date
from decimal import ROUND_FLOOR, Decimal

EARLY_CLOSE_RATE_FACTOR = Decimal("0.5")  # 만기 전 중도 해지는 금리의 절반
DAYS_PER_YEAR = 365


def calc_interest(
    deposits: list[tuple[date, int]], annual_rate_pct: Decimal, close_date: date, maturity_date: date
) -> int:
    """deposits: (입금일 KST, 금액) 목록. 경과일은 입금일부터 min(해지일, 만기일)까지라서 만기 후에는 이자가 늘지 않는다.

    만기일 당일 이후 해지는 전체 금리, 그 전 해지는 금리의 절반이다. 원 미만은 버린다.
    """
    rate = Decimal(annual_rate_pct) / 100
    if close_date < maturity_date:
        rate *= EARLY_CLOSE_RATE_FACTOR
    end = min(close_date, maturity_date)
    total = sum(
        (Decimal(amount) * rate * max((end - day).days, 0) / DAYS_PER_YEAR for day, amount in deposits),
        Decimal(0),
    )
    return int(total.to_integral_value(rounding=ROUND_FLOOR))


def scheduled_payment_days(today: date, maturity: date, day_of_month: int) -> list[date]:
    """오늘 이후 ~ 만기일까지 매월 납입일 (해당 달에 그 날이 없으면 말일). 적금 만기 예상 이자 계산용."""
    days, year, month = [], today.year, today.month
    while date(year, month, 1) <= maturity:
        day = date(year, month, min(day_of_month, calendar.monthrange(year, month)[1]))
        if today < day <= maturity:
            days.append(day)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return days
