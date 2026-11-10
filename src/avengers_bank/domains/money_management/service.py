"""돈 관리 분석과 사용자 수정. 숫자는 analytics·recurring이 계산하고, LLM은 가맹점 분류에만 쓴다.

LLM 호출은 DB 트랜잭션 밖에서 한다 (느린 외부 호출 동안 잠금·커넥션을 잡지 않는다).
"""

import logging
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.exceptions import ApiException
from avengers_bank.core.timezone import kst_start_utc, today_kst
from avengers_bank.domains.money_management import analytics, recurring
from avengers_bank.domains.money_management.classification import classify_merchants, resolve
from avengers_bank.domains.money_management.domain import LABELS, Category, RecurringRule, Source, Txn
from avengers_bank.domains.money_management.models import CategoryRule, RecurringItem, TransactionOverride
from avengers_bank.domains.money_management.repository import money_repository as repo
from avengers_bank.domains.money_management.repository import to_rule
from avengers_bank.domains.money_management.schemas import (
    CategoryDetailResponse,
    CategoryUpdate,
    RecurringCandidate,
    RecurringCreate,
    RecurringDismiss,
    RecurringItemOut,
    RecurringResponse,
    RecurringUpdate,
    SummaryResponse,
    TxnDetailResponse,
    TxnItem,
)
from avengers_bank.domains.users.schemas import UserResponse

logger = logging.getLogger(__name__)

HISTORY_MONTHS = 3  # 비교 기준으로 읽는 과거 달 수


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def parse_month(month: str | None) -> date:
    """'YYYY-MM' → 그 달 1일. 비우면 이번 달. 미래 달은 분석할 거래가 없어 거절한다."""
    today = today_kst()
    if not month:
        return today.replace(day=1)
    try:
        first = datetime.strptime(month, "%Y-%m").date()
    except ValueError as e:
        raise ApiException(400, "INVALID_MONTH", "월은 YYYY-MM 형식으로 보내 주세요.") from e
    if first > today:
        raise ApiException(400, "FUTURE_MONTH", "아직 오지 않은 달은 분석할 수 없습니다.")
    return first


def to_item(t: Txn) -> TxnItem:
    return TxnItem(
        source=t.source, source_id=t.source_id, occurred_at=t.occurred_at, merchant=t.merchant, amount=t.amount,
        direction=t.direction, category=t.category, category_label=LABELS[t.category] if t.category else None,
        category_source=t.category_source, is_one_off=t.is_one_off, payment_label=t.payment_label,
    )


def _newest(txns: list[Txn]) -> list[Txn]:
    return sorted(txns, key=lambda t: t.occurred_at, reverse=True)


def _in_month(t: Txn, month: date) -> bool:
    return t.occurred_at.year == month.year and t.occurred_at.month == month.month


def _matches(t: Txn, rule: RecurringRule | RecurringItem) -> bool:
    return rule.merchant_key is not None and t.merchant_key == rule.merchant_key and t.direction == rule.direction


class MoneyService:
    async def _categorize(self, db: AsyncSession, user: UserResponse, txns: list[Txn], client) -> None:
        """우선순위: 거래 수정 → 사용자 규칙 → 저장된 가맹점 분류 → LLM → 미분류."""
        async with db.begin():
            overrides = await repo.overrides(db, user.user_id)
            rules = await repo.rules(db, user.user_id)
            card_keys = {t.merchant_key for t in txns if t.source != "checking" and t.merchant_key}
            cache = await repo.cached_categories(db, card_keys - rules.keys())

        unknown = {t.merchant_key: t.merchant for t in txns if t.source != "checking" and t.merchant_key
                   and t.merchant_key not in rules and t.merchant_key not in cache
                   and (overrides.get((t.source, t.source_id)) is None or overrides[(t.source, t.source_id)].category is None)}
        if unknown and client is not None:
            # 실패하면 빈 결과: 그 가맹점은 미분류로 두고 다음 조회 때 다시 시도한다
            found = await classify_merchants(list(unknown.values()), client)
            if found:
                async with db.begin():
                    await repo.save_categories(db, found)
                cache.update({k: c for k, (c, _) in found.items()})

        for t in txns:
            o = overrides.get((t.source, t.source_id))
            t.is_one_off = bool(o and o.is_one_off)
            override = Category(o.category) if o and o.category else None
            t.category, t.category_source = resolve(t, override, rules, cache)

    async def _context(self, db: AsyncSession, user: UserResponse, month: date, client) -> tuple[list[Txn], list[RecurringRule], list[RecurringItem]]:
        """선택한 달과 그 앞 3개월의 분류된 거래, 정기 거래."""
        start = kst_start_utc(_add_months(month, -HISTORY_MONTHS))
        end = kst_start_utc(_add_months(month, 1))
        async with db.begin():
            txns = await repo.load_txns(db, user, start, end)
            items = await repo.recurring_items(db, user.user_id)
        await self._categorize(db, user, txns, client)
        return txns, [to_rule(i) for i in items], items

    def _recurring_out(self, item: RecurringItem, txns: list[Txn]) -> RecurringItemOut:
        cat = Category(item.category) if item.category else None
        return RecurringItemOut(
            recurring_id=item.recurring_id, name=item.name, merchant_key=item.merchant_key, direction=item.direction,
            category=cat, category_label=LABELS[cat] if cat else None, amount=item.amount,
            day_of_month=item.day_of_month, status=item.status, skip_month=item.skip_month,
            transactions=[to_item(t) for t in _newest([t for t in txns if _matches(t, item)])],
        )

    async def summary(self, db: AsyncSession, user: UserResponse, month: date, client) -> SummaryResponse:
        today = today_kst()
        txns, rules, _ = await self._context(db, user, month, client)
        async with db.begin():
            bills = await repo.unpaid_bills(db, user.user_id)
        forecast, pace, categories, remaining = analytics.compute(month, today, txns, rules)
        scheduled = recurring.schedule(month, today, rules, bills, txns)
        candidates = recurring.detect_candidates(txns, rules, today)
        this_month = [t for t in txns if _in_month(t, month) and t.is_spending]
        return SummaryResponse(
            month=month.strftime("%Y-%m"), refreshed_at=datetime.now(timezone.utc), forecast=forecast, pace=pace,
            upcoming=scheduled[:3], upcoming_total=len(scheduled), categories=categories,
            remaining_recurring_items=remaining,
            one_off_transactions=[to_item(t) for t in _newest([t for t in this_month if t.is_one_off])],
            review_count=sum(t.category == Category.UNCLASSIFIED for t in this_month) + len(candidates),
        )

    async def schedule(self, db: AsyncSession, user: UserResponse, month: date):
        today = today_kst()
        # 일정은 분류가 필요 없다 (LLM을 부르지 않는다)
        async with db.begin():
            start, end = kst_start_utc(month), kst_start_utc(_add_months(month, 1))
            txns = await repo.load_txns(db, user, start, end)
            rules = [to_rule(i) for i in await repo.recurring_items(db, user.user_id)]
            bills = await repo.unpaid_bills(db, user.user_id)
        return recurring.schedule(month, today, rules, bills, txns)

    async def category(self, db: AsyncSession, user: UserResponse, category: Category, month: date, client) -> CategoryDetailResponse:
        today = today_kst()
        txns, _, _ = await self._context(db, user, month, client)
        spend, baseline, monthly, merchants = analytics.category_detail(month, today, txns, category)
        mine = [t for t in txns if _in_month(t, month) and t.is_spending and (t.category or Category.UNCLASSIFIED) == category]
        return CategoryDetailResponse(
            month=month.strftime("%Y-%m"), spend=spend, baseline=baseline, monthly=monthly, merchants=merchants,
            transactions=[to_item(t) for t in _newest(mine)],
        )

    async def transaction(self, db: AsyncSession, user: UserResponse, source: Source, source_id: int, client=None) -> TxnDetailResponse:
        async with db.begin():
            found = await repo.load_txns(db, user, None, None, source=source, source_id=source_id)
            if not found:
                # 남의 거래도 같은 404 (존재 여부를 알리지 않는다)
                raise ApiException(404, "TRANSACTION_NOT_FOUND", "거래를 찾을 수 없습니다.")
            items = await repo.recurring_items(db, user.user_id)
        t = found[0]
        await self._categorize(db, user, [t], client)
        async with db.begin():
            has_rule = bool(t.merchant_key and await repo.find_rule(db, user.user_id, t.merchant_key))
        linked = next((i for i in items if i.status != "DISMISSED" and _matches(t, i)), None)
        recurring_out = None
        if linked:
            month = t.occurred_at.date().replace(day=1)
            ctx, _, _ = await self._context(db, user, max(month, today_kst().replace(day=1)), client)
            recurring_out = self._recurring_out(linked, ctx)
        return TxnDetailResponse(transaction=to_item(t), merchant_key=t.merchant_key, has_merchant_rule=has_rule, recurring=recurring_out)

    async def _override(self, db: AsyncSession, user_id: int, source: str, source_id: int) -> TransactionOverride:
        o = await repo.find_override(db, user_id, source, source_id)
        if o is None:
            o = TransactionOverride(user_id=user_id, source=source, source_id=source_id, is_one_off=False)
            db.add(o)
        return o

    async def _require_txn(self, db: AsyncSession, user: UserResponse, source: Source, source_id: int) -> Txn:
        found = await repo.load_txns(db, user, None, None, source=source, source_id=source_id)
        if not found:
            raise ApiException(404, "TRANSACTION_NOT_FOUND", "거래를 찾을 수 없습니다.")
        return found[0]

    async def set_category(self, db: AsyncSession, user: UserResponse, source: Source, source_id: int, body: CategoryUpdate) -> TxnDetailResponse:
        """분석용 분류만 바꾼다. 실제 계좌·카드 거래 원본은 그대로다."""
        async with db.begin():
            t = await self._require_txn(db, user, source, source_id)
            if body.scope == "THIS":
                (await self._override(db, user.user_id, source, source_id)).category = body.category.value
            else:
                if not t.merchant_key:
                    raise ApiException(400, "NO_MERCHANT", "결제처 이름이 없는 거래는 이 거래만 바꿀 수 있습니다.")
                rule = await repo.find_rule(db, user.user_id, t.merchant_key)
                if rule is None:
                    db.add(CategoryRule(user_id=user.user_id, merchant_key=t.merchant_key, category=body.category.value))
                else:
                    rule.category = body.category.value
                # 이 거래에 남은 개별 수정이 규칙을 가리지 않게 지운다 (일회성 표시는 유지)
                o = await repo.find_override(db, user.user_id, source, source_id)
                if o is not None:
                    o.category = None
        return await self.transaction(db, user, source, source_id)

    async def set_one_off(self, db: AsyncSession, user: UserResponse, source: Source, source_id: int, is_one_off: bool) -> TxnDetailResponse:
        """일회성 표시: 이번 달 실제 소비에는 그대로 포함하고, 평소 생활비 추정에서만 뺀다."""
        async with db.begin():
            await self._require_txn(db, user, source, source_id)
            (await self._override(db, user.user_id, source, source_id)).is_one_off = is_one_off
        return await self.transaction(db, user, source, source_id)

    async def recurring(self, db: AsyncSession, user: UserResponse, client) -> RecurringResponse:
        today = today_kst()
        txns, rules, items = await self._context(db, user, today.replace(day=1), client)
        candidates = [
            RecurringCandidate(
                merchant_key=c.merchant_key, name=c.name, direction=c.direction, category=c.category,
                category_label=LABELS[c.category] if c.category else None, amount=c.amount,
                day_of_month=c.day_of_month, occurrences=c.occurrences, months_observed=c.months_observed,
                pattern_confirmed=c.pattern_confirmed, transactions=[to_item(t) for t in c.txns],
            )
            for c in recurring.detect_candidates(txns, rules, today)
        ]
        registered = [self._recurring_out(i, txns) for i in items if i.status != "DISMISSED"]
        return RecurringResponse(candidates=candidates, registered=registered)

    async def _item_out(self, db: AsyncSession, user: UserResponse, recurring_id: int) -> RecurringItemOut:
        txns, _, items = await self._context(db, user, today_kst().replace(day=1), None)
        item = next(i for i in items if i.recurring_id == recurring_id)
        return self._recurring_out(item, txns)

    async def add_recurring(self, db: AsyncSession, user: UserResponse, body: RecurringCreate) -> RecurringItemOut:
        async with db.begin():
            item = None
            if body.merchant_key:  # 후보 등록: '반복 거래 아님'으로 숨긴 같은 결제처가 있으면 되살린다
                item = await repo.find_recurring_by_key(db, user.user_id, body.merchant_key, body.direction)
            if item is None:
                item = RecurringItem(user_id=user.user_id, merchant_key=body.merchant_key, direction=body.direction)
                db.add(item)
            item.name, item.amount, item.day_of_month = body.name, body.amount, body.day_of_month
            item.category = body.category.value if body.category else None
            item.status, item.skip_month = "ACTIVE", None
            await db.flush()
            recurring_id = item.recurring_id
        return await self._item_out(db, user, recurring_id)

    async def update_recurring(self, db: AsyncSession, user: UserResponse, recurring_id: int, body: RecurringUpdate) -> RecurringItemOut:
        async with db.begin():
            item = await repo.find_recurring(db, user.user_id, recurring_id)
            if item is None or item.status == "DISMISSED":
                raise ApiException(404, "RECURRING_NOT_FOUND", "정기 거래를 찾을 수 없습니다.")
            fields = body.model_dump(exclude_unset=True, exclude={"clear_skip"})
            for key, value in fields.items():
                setattr(item, key, value.value if isinstance(value, Category) else value)
            if body.clear_skip:
                item.skip_month = None
        return await self._item_out(db, user, recurring_id)

    async def dismiss(self, db: AsyncSession, user: UserResponse, body: RecurringDismiss) -> None:
        """'반복 거래 아님': 같은 결제처를 후보로 다시 띄우지 않는다."""
        async with db.begin():
            item = await repo.find_recurring_by_key(db, user.user_id, body.merchant_key, body.direction)
            if item is None:
                db.add(RecurringItem(
                    user_id=user.user_id, name=body.name, merchant_key=body.merchant_key, direction=body.direction,
                    amount=0, day_of_month=1, status="DISMISSED",
                ))
            elif item.status != "ACTIVE":
                item.status = "DISMISSED"


money_service = MoneyService()
