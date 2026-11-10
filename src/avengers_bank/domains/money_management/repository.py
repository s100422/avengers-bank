"""원본 거래(계좌·카드)를 읽어 분석용 Txn으로 바꾸고, 돈 관리 분석 정보를 읽고 쓴다. 원본은 읽기만 한다."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.accounts.kinds import INTERBANK_IN, INTERBANK_OUT, KINDS as ACCOUNT_KINDS
from avengers_bank.domains.accounts.models import CheckingAccount, CheckingAccountHistory
from avengers_bank.domains.agent.tools.common import to_kst
from avengers_bank.domains.cards.models import CreditCard, CreditCardBill, CreditCardHistory, DebitCard, DebitCardHistory
from avengers_bank.domains.money_management.classification import merchant_key
from avengers_bank.domains.money_management.domain import (
    INCOME_CHECKING_TYPES,
    SPENDING_CHECKING_TYPES,
    Bill,
    Category,
    RecurringRule,
    Source,
    Txn,
)
from avengers_bank.domains.money_management.models import CategoryRule, MerchantCategory, RecurringItem, TransactionOverride
from avengers_bank.domains.users.schemas import UserResponse

_INTERBANK = {INTERBANK_OUT, INTERBANK_IN}


def _last4(num: str) -> str:
    digits = [c for c in num if c.isdigit()]
    return "".join(digits[-4:])


def _key(name: str | None) -> str | None:
    return (merchant_key(name) or None) if name else None


class MoneyRepository:
    async def _own_account_nums(self, db: AsyncSession, user_id: int) -> set[str]:
        nums: set[str] = set()
        for kind in ACCOUNT_KINDS.values():
            nums.update(await db.scalars(select(kind.model.account_num).where(kind.model.user_id == user_id)))
        return nums

    async def load_txns(
        self, db: AsyncSession, user: UserResponse, start: datetime | None, end: datetime | None,
        source: Source | None = None, source_id: int | None = None,
    ) -> list[Txn]:
        """[start, end) 기간의 카드 사용내역과 입출금 계좌 내역 (분류 전). source·source_id를 주면 그 한 건만."""
        out: list[Txn] = []
        one = source is not None

        if not one or source == "checking":
            own = await self._own_account_nums(db, user.user_id)
            stmt = (
                select(CheckingAccountHistory, CheckingAccount)
                .join(CheckingAccount, CheckingAccount.checking_account_id == CheckingAccountHistory.checking_account_id)
                .where(CheckingAccount.user_id == user.user_id)
            )
            stmt = (stmt.where(CheckingAccountHistory.checking_account_history_id == source_id) if one
                    else stmt.where(CheckingAccountHistory.date >= start, CheckingAccountHistory.date < end))
            for h, acc in (await db.execute(stmt)).all():
                if h.type not in SPENDING_CHECKING_TYPES | INCOME_CHECKING_TYPES:
                    continue  # 저축 이동·카드 결제/대금·충전·해지금은 분석·반복 탐지에 쓰지 않는다
                # 본인 이동: 내 계좌번호로 오간 이체, 타행은 내 계좌 목록이 없어 이름으로 판단 (사용자 결정, 동명이인은 화면에서 되돌림)
                is_self = h.counterpart_account in own or (h.type in _INTERBANK and h.counterpart_name == user.name)
                out.append(Txn(
                    source="checking", source_id=h.checking_account_history_id, occurred_at=to_kst(h.date),
                    amount=h.amount, direction="OUT" if h.type in SPENDING_CHECKING_TYPES else "IN",
                    merchant=h.counterpart_name, merchant_key=_key(h.counterpart_name), checking_type=h.type,
                    payment_label=f"{acc.nickname or '입출금'} ****{_last4(acc.account_num)}", is_self_transfer=is_self,
                ))

        for src, card_model, hist_model, card_id_col, hist_id_col, label in (
            ("credit", CreditCard, CreditCardHistory, "credit_card_id", "credit_card_history_id", "신용카드"),
            ("debit", DebitCard, DebitCardHistory, "debit_card_id", "debit_card_history_id", "체크카드"),
        ):
            if one and source != src:
                continue
            hist_id = getattr(hist_model, hist_id_col)
            stmt = (
                select(hist_model, card_model)
                .join(card_model, getattr(card_model, card_id_col) == getattr(hist_model, card_id_col))
                .where(card_model.user_id == user.user_id)
            )
            stmt = stmt.where(hist_id == source_id) if one else stmt.where(hist_model.time >= start, hist_model.time < end)
            for h, card in (await db.execute(stmt)).all():
                out.append(Txn(
                    source=src, source_id=getattr(h, hist_id_col), occurred_at=to_kst(h.time), amount=h.used_amount,
                    direction="OUT", merchant=h.place_of_use, merchant_key=_key(h.place_of_use), checking_type=None,
                    payment_label=f"{label} ****{_last4(card.card_num)}",
                ))
        return out

    async def unpaid_bills(self, db: AsyncSession, user_id: int) -> list[Bill]:
        rows = (await db.execute(
            select(CreditCardBill, CreditCard)
            .join(CreditCard, CreditCard.credit_card_id == CreditCardBill.credit_card_id)
            .where(CreditCard.user_id == user_id, CreditCardBill.status == "UNPAID")
        )).all()
        return [Bill(b.bill_id, b.due_date, b.total_amount, f"신용카드 ****{_last4(c.card_num)}", c.credit_card_id) for b, c in rows]

    async def overrides(self, db: AsyncSession, user_id: int) -> dict[tuple[str, int], TransactionOverride]:
        rows = await db.scalars(select(TransactionOverride).where(TransactionOverride.user_id == user_id))
        return {(o.source, o.source_id): o for o in rows}

    async def find_override(self, db: AsyncSession, user_id: int, source: str, source_id: int) -> TransactionOverride | None:
        return await db.scalar(select(TransactionOverride).where(
            TransactionOverride.user_id == user_id, TransactionOverride.source == source,
            TransactionOverride.source_id == source_id,
        ))

    async def rules(self, db: AsyncSession, user_id: int) -> dict[str, Category]:
        rows = await db.scalars(select(CategoryRule).where(CategoryRule.user_id == user_id))
        return {r.merchant_key: Category(r.category) for r in rows}

    async def find_rule(self, db: AsyncSession, user_id: int, key: str) -> CategoryRule | None:
        return await db.scalar(select(CategoryRule).where(CategoryRule.user_id == user_id, CategoryRule.merchant_key == key))

    async def cached_categories(self, db: AsyncSession, keys: set[str]) -> dict[str, Category]:
        if not keys:
            return {}
        rows = await db.scalars(select(MerchantCategory).where(MerchantCategory.merchant_key.in_(keys)))
        return {r.merchant_key: Category(r.category) for r in rows}

    async def save_categories(self, db: AsyncSession, found: dict[str, tuple[Category, str]]) -> None:
        """동시에 같은 가맹점을 분류해도 먼저 저장된 값을 둔다 (이름만 보고 정한 값이라 어느 쪽이든 같다)."""
        if not found:
            return
        insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
        await db.execute(insert(MerchantCategory).values([
            {"merchant_key": k, "category": c.value, "reason": r[:200]} for k, (c, r) in found.items()
        ]).on_conflict_do_nothing(index_elements=["merchant_key"]))

    async def recurring_items(self, db: AsyncSession, user_id: int) -> list[RecurringItem]:
        return list(await db.scalars(
            select(RecurringItem).where(RecurringItem.user_id == user_id).order_by(RecurringItem.recurring_id)
        ))

    async def find_recurring(self, db: AsyncSession, user_id: int, recurring_id: int) -> RecurringItem | None:
        return await db.scalar(select(RecurringItem).where(
            RecurringItem.user_id == user_id, RecurringItem.recurring_id == recurring_id,
        ))

    async def find_recurring_by_key(self, db: AsyncSession, user_id: int, key: str, direction: str) -> RecurringItem | None:
        return await db.scalar(select(RecurringItem).where(
            RecurringItem.user_id == user_id, RecurringItem.merchant_key == key, RecurringItem.direction == direction,
        ))


def to_rule(item: RecurringItem) -> RecurringRule:
    return RecurringRule(
        recurring_id=item.recurring_id, name=item.name, merchant_key=item.merchant_key, direction=item.direction,
        category=Category(item.category) if item.category else None, amount=item.amount,
        day_of_month=item.day_of_month, status=item.status, skip_month=item.skip_month,
    )


money_repository = MoneyRepository()
