from datetime import date, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.cards.kinds import CardKind
from avengers_bank.domains.cards.models import CreditCardBill, CreditCardHistory


class CardRepository:
    async def save(self, db: AsyncSession, card):
        db.add(card)
        await db.flush()
        return card

    async def save_history(self, db: AsyncSession, history):
        db.add(history)
        await db.flush()
        return history

    async def find_by_id(self, db: AsyncSession, kind: CardKind, card_id: int):
        return await db.get(kind.model, card_id)

    async def find_by_user_id(self, db: AsyncSession, kind: CardKind, user_id: int) -> list:
        id_col = getattr(kind.model, kind.id_column)
        stmt = select(kind.model).where(kind.model.user_id == user_id).order_by(id_col)
        return list(await db.scalars(stmt))

    async def find_histories(
        self, db: AsyncSession, kind: CardKind, card_id: int, limit: int, offset: int
    ) -> list:
        model = kind.history_model
        stmt = (
            select(model)
            .where(getattr(model, kind.id_column) == card_id)
            .order_by(model.time.desc(), getattr(model, kind.history_id_column).desc())
            .limit(limit)
            .offset(offset)
        )
        return list(await db.scalars(stmt))

    async def lock_card(self, db: AsyncSession, kind: CardKind, card_id: int):
        """카드 행 잠금 (docs/ERD.md 규칙 9). 잠금 순서: 입출금 계좌 → 카드 → 청구서."""
        id_col = getattr(kind.model, kind.id_column)
        stmt = (
            select(kind.model).where(id_col == card_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        return await db.scalar(stmt)

    # ── 신용카드 청구서 ───────────────────────────────────────────────

    async def save_bill(self, db: AsyncSession, bill: CreditCardBill) -> CreditCardBill:
        db.add(bill)
        await db.flush()
        return bill

    async def find_bill_by_id(self, db: AsyncSession, bill_id: int) -> CreditCardBill | None:
        return await db.get(CreditCardBill, bill_id)

    async def lock_bill(self, db: AsyncSession, bill_id: int) -> CreditCardBill | None:
        stmt = (
            select(CreditCardBill).where(CreditCardBill.bill_id == bill_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        return await db.scalar(stmt)

    async def find_bill_by_period(
        self, db: AsyncSession, card_id: int, period_start: date
    ) -> CreditCardBill | None:
        return await db.scalar(
            select(CreditCardBill).where(
                CreditCardBill.credit_card_id == card_id,
                CreditCardBill.period_start == period_start,
            )
        )

    async def find_bills(self, db: AsyncSession, card_id: int) -> list[CreditCardBill]:
        stmt = (
            select(CreditCardBill).where(CreditCardBill.credit_card_id == card_id)
            .order_by(CreditCardBill.period_start.desc())
        )
        return list(await db.scalars(stmt))

    async def find_bill_histories(self, db: AsyncSession, bill_id: int) -> list[CreditCardHistory]:
        stmt = (
            select(CreditCardHistory).where(CreditCardHistory.bill_id == bill_id)
            .order_by(CreditCardHistory.time, CreditCardHistory.credit_card_history_id)
        )
        return list(await db.scalars(stmt))

    def _unbilled_in_period(self, card_id: int, start: datetime, end: datetime):
        """start 이상 end 미만에 쓴, 아직 청구되지 않은(bill_id IS NULL) 사용내역 조건."""
        return (
            CreditCardHistory.credit_card_id == card_id,
            CreditCardHistory.bill_id.is_(None),
            CreditCardHistory.time >= start,
            CreditCardHistory.time < end,
        )

    async def sum_unbilled(self, db: AsyncSession, card_id: int, start: datetime, end: datetime) -> int:
        stmt = select(func.coalesce(func.sum(CreditCardHistory.used_amount), 0)).where(
            *self._unbilled_in_period(card_id, start, end)
        )
        return int(await db.scalar(stmt))  # PostgreSQL의 SUM(bigint)는 Decimal로 온다

    async def assign_bill(
        self, db: AsyncSession, card_id: int, bill_id: int, start: datetime, end: datetime
    ) -> None:
        stmt = (
            update(CreditCardHistory)
            .where(*self._unbilled_in_period(card_id, start, end))
            .values(bill_id=bill_id)
        )
        await db.execute(stmt)


card_repository = CardRepository()
