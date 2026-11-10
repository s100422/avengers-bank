"""돈 관리 API 요청·응답. 프론트엔드 타입(frontend/lib/money.ts)과 1:1로 맞춘다.

금액 표시 원칙: 실제(actual) · 확정(CONFIRMED) · 추정(ESTIMATED)을 필드 이름과 status로 구분한다.
비교할 과거 데이터가 없으면 비교 값은 None이다 (임의 평균을 만들지 않는다).
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from avengers_bank.domains.money_management.domain import Category, CategorySource, Direction, Source

PaceStatus = Literal["HIGHER", "NORMAL", "LOWER", "UNKNOWN"]  # UNKNOWN = 비교 데이터 부족


class Baseline(BaseModel):
    """비교 기준. months=0이면 비교 데이터 없음, 1이면 '지난달 기준', 2~3이면 '최근 N개월 평균'."""

    months: int
    period_start: date | None  # 기준에 쓴 첫 달 1일
    period_end: date | None  # 기준에 쓴 마지막 달 말일
    monthly_avg: int | None  # 월평균 소비 (일회성 지출 제외)


class TxnItem(BaseModel):
    source: Source
    source_id: int
    occurred_at: datetime  # KST
    merchant: str | None
    amount: int  # 양수
    direction: Direction
    category: Category | None  # 소비가 아닌 거래(본인 이동 등)는 None
    category_label: str | None
    category_source: CategorySource
    is_one_off: bool
    payment_label: str


class ScheduledItem(BaseModel):
    """입출금 예정 내역. CARD_BILL은 미납 청구서(확정), RECURRING은 정기 거래 추정."""

    key: str  # "bill:12" / "recurring:3"
    kind: Literal["CARD_BILL", "RECURRING"]
    name: str
    date: date
    amount: int  # 양수
    direction: Direction
    status: Literal["CONFIRMED", "ESTIMATED"]
    account_label: str | None
    recurring_id: int | None = None
    bill_id: int | None = None


class Forecast(BaseModel):
    """이번 달 예상 지출 = 실제 소비 + 남은 정기 지출 + 남은 예상 변동지출. 카드대금은 넣지 않는다."""

    is_current_month: bool  # 지난 달이면 projected_total == actual_to_date, 남은 값은 0
    actual_to_date: int
    remaining_recurring: int
    remaining_variable: int
    projected_total: int
    variable_basis: Literal["BASELINE", "THIS_MONTH", "NONE"]  # 남은 변동지출을 무엇으로 추정했는지
    baseline: Baseline
    change_rate: float | None  # (projected_total - monthly_avg) / monthly_avg. 기준 없으면 None


class Pace(BaseModel):
    """평소와 비교. 각 리스트의 i번째는 (i+1)일까지의 누적 소비."""

    status: PaceStatus
    diff_rate: float | None  # 오늘까지 실제 누적 vs 과거 같은 일자 평균 누적
    today_day: int  # 선택한 달에서 마지막 실제 데이터 일자 (지난 달이면 말일)
    days_in_month: int
    actual_cumulative: list[int]  # 길이 today_day
    projected_cumulative: list[int]  # 길이 days_in_month - today_day (지난 달이면 빈 리스트)
    baseline_cumulative: list[int] | None  # 길이 days_in_month, 기준 없으면 None


class CategorySpend(BaseModel):
    category: Category
    label: str
    actual: int  # 오늘까지(지난 달이면 그 달 전체) 실제 소비
    baseline_to_date: int | None  # 평소 같은 시점 누적 평균
    diff: int | None  # actual - baseline_to_date
    projected: int | None  # 이 항목의 월말 예상
    status: PaceStatus


class SummaryResponse(BaseModel):
    """돈 관리 탭 요약 + 이번 달 분석 상세 화면이 같이 쓴다."""

    month: str  # "YYYY-MM"
    refreshed_at: datetime
    forecast: Forecast
    pace: Pace
    upcoming: list[ScheduledItem]  # 오늘 이후 가장 가까운 3건
    upcoming_total: int  # 이번 달 남은 예정 내역 전체 건수
    categories: list[CategorySpend]  # 평소와 차이가 큰 항목부터 (기준 없으면 사용액 큰 순)
    remaining_recurring_items: list[ScheduledItem]  # remaining_recurring에 포함된 정기 지출
    one_off_transactions: list[TxnItem]  # 이번 달 일회성 지출 (평소 추정에서 제외한 것)
    review_count: int  # 확인 필요: 이번 달 미분류 거래 + 반복 거래 후보


class MonthAmount(BaseModel):
    month: str  # "YYYY-MM"
    amount: int


class MerchantSpend(BaseModel):
    merchant: str
    amount: int
    count: int


class CategoryDetailResponse(BaseModel):
    month: str
    spend: CategorySpend
    baseline: Baseline
    monthly: list[MonthAmount]  # 기준 기간 각 달 + 선택한 달 (오래된 순)
    merchants: list[MerchantSpend]  # 사용처별 합계, 큰 순
    transactions: list[TxnItem]  # 최신순


class RecurringItemOut(BaseModel):
    recurring_id: int
    name: str
    merchant_key: str | None
    direction: Direction
    category: Category | None
    category_label: str | None
    amount: int
    day_of_month: int
    status: Literal["ACTIVE", "EXCLUDED"]
    skip_month: str | None
    transactions: list[TxnItem]  # 반복 판단·연결에 쓴 실제 거래 (최신순)


class RecurringCandidate(BaseModel):
    """자동 탐지한 반복 거래 후보."""

    merchant_key: str
    name: str
    direction: Direction
    category: Category | None
    category_label: str | None
    amount: int  # 최근 금액
    day_of_month: int  # 관측된 결제일의 대표값
    occurrences: int
    months_observed: int
    pattern_confirmed: bool  # 여러 달에 걸쳐 주기가 확인됨. False면 '반복 결제 후보'로만 표시
    transactions: list[TxnItem]


class RecurringResponse(BaseModel):
    candidates: list[RecurringCandidate]
    registered: list[RecurringItemOut]


class TxnDetailResponse(BaseModel):
    transaction: TxnItem
    merchant_key: str | None
    has_merchant_rule: bool  # 이 결제처에 사용자 규칙이 있음
    recurring: RecurringItemOut | None


# ---- 요청 ----

class CategoryUpdate(BaseModel):
    category: Category
    scope: Literal["THIS", "MERCHANT"]  # 이번 거래만 / 이 결제처에 앞으로 적용


class OneOffUpdate(BaseModel):
    is_one_off: bool


class RecurringCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    direction: Direction
    category: Category | None = None
    amount: int = Field(ge=0, le=1_000_000_000)
    day_of_month: int = Field(ge=1, le=31)
    merchant_key: str | None = Field(default=None, max_length=100)  # 후보를 등록할 때


class RecurringUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    category: Category | None = None
    amount: int | None = Field(default=None, ge=0, le=1_000_000_000)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    status: Literal["ACTIVE", "EXCLUDED"] | None = None
    skip_month: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    clear_skip: bool = False  # True면 skip_month를 지운다


class RecurringDismiss(BaseModel):
    merchant_key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    direction: Direction
