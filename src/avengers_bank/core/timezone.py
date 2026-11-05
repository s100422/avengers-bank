from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def today_kst() -> date:
    return datetime.now(KST).date()


def kst_start_utc(day: date) -> datetime:
    """그날 00:00 KST를 UTC 시각으로 바꾼 값. DB의 시각 비교는 UTC로 통일한다."""
    return datetime.combine(day, time.min, tzinfo=KST).astimezone(timezone.utc)


def today_start_utc() -> datetime:
    """오늘 00:00 KST (UTC). 1일 이체 한도 합계의 시작점이다 (ERD 규칙 7)."""
    return kst_start_utc(today_kst())
