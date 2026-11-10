"""돈 관리 분석 조회 Tool. 숫자는 money_service가 계산한 값을 그대로 넘기고, 모델은 설명만 한다.

화면용 누적 배열·결제수단 라벨(카드 끝자리)은 빼고 설명에 필요한 값만 추린다.
분류 client는 None: 저장된 가맹점 분류만 쓰고, 도구 실행 중에 LLM을 또 부르지 않는다.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.agent.tools.common import ToolArgs
from avengers_bank.domains.money_management.domain import LABELS, Category, CategorySource, Direction
from avengers_bank.domains.money_management.schemas import Baseline, CategorySpend, MerchantSpend, MonthAmount, ScheduledItem, TxnItem
from avengers_bank.domains.money_management.service import money_service, parse_month
from avengers_bank.domains.users.schemas import UserResponse

MONTH_DESC = "분석할 달 YYYY-MM. 비우면 이번 달"
MAX_TXNS = 20
_BY_LABEL = {label: c for c, label in LABELS.items()}


class MonthArgs(ToolArgs):
    month: str | None = Field(default=None, description=MONTH_DESC)


class CategoryArgs(ToolArgs):
    category: str = Field(description="카테고리 코드 또는 한글 이름: " + ", ".join(f"{c.value}({label})" for c, label in LABELS.items()))
    month: str | None = Field(default=None, description=MONTH_DESC)

    @field_validator("category")
    @classmethod
    def _to_code(cls, v: str) -> str:
        v = v.strip()
        if v.upper() in Category.__members__:
            return v.upper()
        if v in _BY_LABEL:
            return _BY_LABEL[v].value
        raise ValueError("없는 카테고리입니다. 설명에 있는 코드나 이름을 쓰세요.")


class Txn(BaseModel):
    merchant: str | None
    amount: int
    date: datetime  # KST


class CategoryTxn(Txn):
    category_source: CategorySource  # OVERRIDE/RULE=사용자가 지정, LLM=자동 분류, NONE=미분류


class Scheduled(BaseModel):
    kind: Literal["CARD_BILL", "RECURRING"]
    name: str
    date: date
    amount: int
    direction: Direction
    status: Literal["CONFIRMED", "ESTIMATED"]  # CARD_BILL=확정 청구, RECURRING=추정


def _txn(t: TxnItem) -> Txn:
    return Txn(merchant=t.merchant, amount=t.amount, date=t.occurred_at)


def _scheduled(s: ScheduledItem) -> Scheduled:
    return Scheduled(kind=s.kind, name=s.name, date=s.date, amount=s.amount, direction=s.direction, status=s.status)


class ForecastOut(BaseModel):
    is_current_month: bool
    actual_to_date: int  # 실제: 지금까지 쓴 돈
    remaining_recurring: int  # 예상: 남은 정기 지출
    remaining_variable: int  # 예상: 남은 변동 지출
    projected_total: int  # 예상: 월말 추정 합계 (카드대금 제외)
    baseline: Baseline  # months=0 비교 없음, 1 지난달 기준, 2~3 최근 N개월 평균
    change_rate: float | None  # projected_total vs baseline.monthly_avg


class SpendingAnalysis(BaseModel):
    month: str
    forecast: ForecastOut
    pace_status: Literal["HIGHER", "NORMAL", "LOWER", "UNKNOWN"]
    pace_diff_rate: float | None  # 오늘까지 실제 누적 vs 평소 같은 날짜 누적
    categories: list[CategorySpend]  # 평소와 차이가 큰 항목부터
    remaining_recurring_items: list[Scheduled]
    one_off_transactions: list[Txn]


async def get_spending_analysis(db: AsyncSession, user: UserResponse, args: MonthArgs) -> SpendingAnalysis:
    s = await money_service.summary(db, user, parse_month(args.month), None)
    f = s.forecast
    return SpendingAnalysis(
        month=s.month,
        forecast=ForecastOut(
            is_current_month=f.is_current_month, actual_to_date=f.actual_to_date, remaining_recurring=f.remaining_recurring,
            remaining_variable=f.remaining_variable, projected_total=f.projected_total, baseline=f.baseline, change_rate=f.change_rate,
        ),
        pace_status=s.pace.status, pace_diff_rate=s.pace.diff_rate, categories=s.categories,
        remaining_recurring_items=[_scheduled(i) for i in s.remaining_recurring_items],
        one_off_transactions=[_txn(t) for t in s.one_off_transactions],
    )


class CategorySpending(BaseModel):
    month: str
    spend: CategorySpend
    baseline: Baseline
    monthly: list[MonthAmount]  # 오래된 순, 마지막이 선택한 달
    top_merchants: list[MerchantSpend]
    recent_transactions: list[CategoryTxn]  # 최신순, 최대 20건
    transaction_count: int


async def get_category_spending(db: AsyncSession, user: UserResponse, args: CategoryArgs) -> CategorySpending:
    d = await money_service.category(db, user, Category(args.category), parse_month(args.month), None)
    return CategorySpending(
        month=d.month, spend=d.spend, baseline=d.baseline, monthly=d.monthly, top_merchants=d.merchants[:10],
        recent_transactions=[CategoryTxn(merchant=t.merchant, amount=t.amount, date=t.occurred_at, category_source=t.category_source)
                             for t in d.transactions[:MAX_TXNS]],
        transaction_count=len(d.transactions),
    )


class RegisteredRecurring(BaseModel):
    name: str
    amount: int
    day_of_month: int
    status: Literal["ACTIVE", "EXCLUDED"]  # EXCLUDED=사용자가 예상에서 뺌


class Candidate(BaseModel):
    name: str
    amount: int
    day_of_month: int
    pattern_confirmed: bool  # False면 아직 '반복 결제 후보'일 뿐
    occurrences: int


class RecurringAndSchedule(BaseModel):
    month: str
    registered: list[RegisteredRecurring]
    candidates: list[Candidate]
    upcoming: list[Scheduled]  # 선택한 달의 남은 입출금 예정


async def get_recurring_and_schedule(db: AsyncSession, user: UserResponse, args: MonthArgs) -> RecurringAndSchedule:
    month = parse_month(args.month)
    r = await money_service.recurring(db, user, None)  # 등록·후보는 달과 상관없이 현재 기준
    upcoming = await money_service.schedule(db, user, month)
    return RecurringAndSchedule(
        month=month.strftime("%Y-%m"),
        registered=[RegisteredRecurring(name=i.name, amount=i.amount, day_of_month=i.day_of_month, status=i.status) for i in r.registered],
        candidates=[Candidate(name=c.name, amount=c.amount, day_of_month=c.day_of_month, pattern_confirmed=c.pattern_confirmed,
                              occurrences=c.occurrences) for c in r.candidates],
        upcoming=[_scheduled(s) for s in upcoming],
    )
