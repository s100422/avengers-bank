"""인증된 읽기 도구의 결과에서 채팅 카드에 표시할 값만 고른다."""

from datetime import datetime, timezone

from avengers_bank.domains.agent.schemas import FinancialReport, ReportRow, ReportSection, SummaryRow
from avengers_bank.domains.agent.tools.accounts import AccountsResult
from avengers_bank.domains.agent.tools.cards import CardPaymentStatus
from avengers_bank.domains.agent.tools.favorites import FavoriteProductsResult
from avengers_bank.domains.agent.tools.money import CategorySpending, RecurringAndSchedule, SpendingAnalysis
from avengers_bank.domains.agent.tools.summary import FinancialSummary
from avengers_bank.domains.agent.tools.transactions import HistoryResult

ROW_LIMIT = 10
ACCOUNT_LABELS = {"checking": "입출금", "deposit": "예금", "savings": "적금"}
HISTORY_LABELS = {
    "TRANSFER_OUT": "보낸 이체", "TRANSFER_IN": "받은 이체", "TO_SAVINGS": "적금 납입",
    "TO_DEPOSIT": "예금 예치", "CARD_PAYMENT": "카드 결제", "CARD_BILL_PAYMENT": "카드대금 납부",
    "DEV_CHARGE": "충전", "CLOSE_IN": "해지금 입금", "INTEREST": "이자", "CLOSE_OUT": "해지 출금",
}


def won(amount: int) -> str:
    return f"{amount:,}원"


def month_label(month: str) -> str:
    year, number = month.split("-")
    return f"{year}년 {int(number)}월"


def metric(label: str, amount: int) -> SummaryRow:
    return SummaryRow(label=label, value=won(amount))


def amount_row(label: str, amount: int, *, detail: str | None = None, bar: bool = False) -> ReportRow:
    return ReportRow(label=label, value=won(amount), detail=detail, bar_amount=max(0, amount) if bar else None)


def spending_report(result: SpendingAnalysis, captured_at: datetime) -> FinancialReport:
    forecast = result.forecast
    metrics = [metric("지금까지 쓴 돈" if forecast.is_current_month else "한 달 동안 쓴 돈", forecast.actual_to_date)]
    if forecast.is_current_month:
        metrics.append(metric("월말 예상 지출", forecast.projected_total))
    rate = result.pace_diff_rate
    badge, tone = "비교할 지출 내역이 부족해요", "neutral"
    if rate is not None:
        percent = round(abs(rate) * 100)
        if result.pace_status == "NORMAL" or percent == 0:
            badge = "평소와 비슷해요"
        else:
            compare = "평소 같은 시점보다" if forecast.is_current_month else "평소보다"
            badge = f"{compare} {percent}% {'많아요' if rate > 0 else '적어요'}"
            tone = "coral" if rate > 0 else "mint"
    categories = sorted((c for c in result.categories if c.actual > 0), key=lambda c: -c.actual)
    return FinancialReport(
        title=f"{month_label(result.month)} 소비",
        captured_at=captured_at,
        metrics=metrics,
        badge=badge,
        badge_tone=tone,
        sections=[ReportSection(
            title="많이 쓴 항목",
            rows=[amount_row(c.label, c.actual, bar=True) for c in categories],
        )] if categories else [],
    )


def report_from_tool(result: object) -> FinancialReport | None:
    captured_at = datetime.now(timezone.utc)
    if isinstance(result, SpendingAnalysis):
        return spending_report(result, captured_at)

    if isinstance(result, FinancialSummary):
        maturities = [
            amount_row(item.name, item.balance, detail=f"만기 {item.maturity_date.isoformat()}")
            for item in result.maturities[:ROW_LIMIT]
        ]
        sections = [ReportSection(title="계좌 종류별 잔액", rows=[
            amount_row("입출금", result.checking_balance, bar=True),
            amount_row("예금", result.deposit_balance, bar=True),
            amount_row("적금", result.savings_balance, bar=True),
        ])]
        if maturities:
            sections.append(ReportSection(title="가까운 예·적금 만기", rows=maturities))
        return FinancialReport(
            title="내 자산 요약", captured_at=captured_at,
            metrics=[metric("전체 계좌 잔액", result.total_balance),
                     SummaryRow(label="활성 계좌", value=f"{result.active_account_count}개")],
            sections=sections,
        )

    if isinstance(result, AccountsResult):
        return FinancialReport(
            title="내 계좌 잔액", captured_at=captured_at,
            metrics=[SummaryRow(label="활성 계좌", value=f"{len(result.accounts)}개")],
            sections=[ReportSection(title="계좌별 잔액", rows=[
                amount_row(
                    a.name, a.balance,
                    detail=f"{ACCOUNT_LABELS.get(a.account_type, '계좌')} · 만기 {a.maturity_date.isoformat()}"
                    if a.maturity_date else ACCOUNT_LABELS.get(a.account_type, "계좌"),
                ) for a in result.accounts[:ROW_LIMIT]
            ])] if result.accounts else [],
            note=f"계좌 {ROW_LIMIT}개를 표시했어요." if len(result.accounts) > ROW_LIMIT else None,
        )

    if isinstance(result, HistoryResult):
        return FinancialReport(
            title="조회한 거래 내역", captured_at=captured_at,
            sections=[ReportSection(title="최근 거래부터", rows=[
                amount_row(
                    item.counterpart_name or HISTORY_LABELS.get(item.type, "계좌 거래"),
                    item.amount,
                    detail=f"{item.date:%Y-%m-%d %H:%M} · {HISTORY_LABELS.get(item.type, '계좌 거래')}",
                ) for item in result.transactions[:ROW_LIMIT]
            ])] if result.transactions else [],
            note=(
                "조건에 맞는 거래가 없어요." if not result.transactions
                else f"최근 {min(len(result.transactions), ROW_LIMIT)}건을 표시했어요."
                if result.has_more or len(result.transactions) > ROW_LIMIT else None
            ),
        )

    if isinstance(result, CardPaymentStatus):
        return FinancialReport(
            title="카드 결제 현황", captured_at=captured_at,
            metrics=[metric("미납 청구액", result.unpaid_bill_total),
                     metric("전체 미결제액", result.credit_outstanding_total)],
            badge=f"다음 결제 예정일 {result.next_payment_date.isoformat()}" if result.next_payment_date else None,
            sections=[ReportSection(title="결제 계좌 잔액", rows=[
                amount_row(
                    account.name, account.balance,
                    detail=f"미납 청구액 기준 부족액 {won(account.shortfall_for_unpaid_bills)}",
                ) for account in result.payment_accounts[:ROW_LIMIT]
            ])] if result.payment_accounts else [],
        )

    if isinstance(result, CategorySpending):
        spend = result.spend
        return FinancialReport(
            title=f"{month_label(result.month)} {spend.label}", captured_at=captured_at,
            metrics=[metric("실제 지출", spend.actual)] + (
                [metric("평소 같은 기간 지출", spend.baseline_to_date)] if spend.baseline_to_date is not None else []
            ),
            sections=[ReportSection(title="사용처별 지출", rows=[
                amount_row(item.merchant, item.amount, detail=f"{item.count}건", bar=True)
                for item in result.top_merchants
            ])] if result.top_merchants else [],
        )

    if isinstance(result, RecurringAndSchedule):
        sections = []
        if result.upcoming:
            sections.append(ReportSection(title=f"{month_label(result.month)} 입출금 일정", rows=[
                amount_row(
                    item.name, item.amount,
                    detail=f"{item.date.isoformat()} · {'입금' if item.direction == 'IN' else '출금'} · "
                           f"{'확정' if item.status == 'CONFIRMED' else '예상'}",
                ) for item in sorted(result.upcoming, key=lambda item: item.date)[:ROW_LIMIT]
            ]))
        if result.registered:
            sections.append(ReportSection(title="등록된 정기 거래", rows=[
                amount_row(item.name, item.amount, detail=f"매월 {item.day_of_month}일 · {'활성' if item.status == 'ACTIVE' else '제외'}")
                for item in result.registered[:ROW_LIMIT]
            ]))
        if result.candidates:
            sections.append(ReportSection(title="반복 거래 후보", rows=[
                amount_row(item.name, item.amount, detail=f"{item.occurrences}회 발견")
                for item in result.candidates[:ROW_LIMIT]
            ]))
        return FinancialReport(
            title="정기 거래와 예정 일정", captured_at=captured_at, sections=sections,
            note="표시할 정기 거래나 예정 일정이 없어요." if not sections else None,
        )

    if isinstance(result, FavoriteProductsResult):
        return FinancialReport(
            title="찜한 금융상품", captured_at=captured_at,
            metrics=[SummaryRow(label="찜한 상품", value=f"{len(result.favorites)}개")],
            sections=[ReportSection(title="최근에 찜한 순서", rows=[
                ReportRow(
                    label=item.name,
                    value=f"연 {item.interest_rate:g}%" if item.interest_rate is not None
                    else f"한도 {won(item.credit_limit)}" if item.credit_limit is not None else "",
                ) for item in result.favorites[:ROW_LIMIT]
            ])] if result.favorites else [],
            note=f"최근 {ROW_LIMIT}개를 표시했어요." if len(result.favorites) > ROW_LIMIT else None,
        )

    return None
