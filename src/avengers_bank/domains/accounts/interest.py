"""예금·적금 해지 이자 계산 (C-043). 단리, 입금 한 건씩 일할 계산한다."""

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
