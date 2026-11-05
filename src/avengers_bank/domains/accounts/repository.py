from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.accounts.kinds import TRANSFER_OUT, AccountKind
from avengers_bank.domains.accounts.models import CheckingAccount, CheckingAccountHistory


class AccountRepository:
    async def save(self, db: AsyncSession, account):
        db.add(account)
        await db.flush()
        return account

    async def find_by_id(self, db: AsyncSession, kind: AccountKind, account_id: int):
        return await db.get(kind.model, account_id)

    async def find_by_user_id(self, db: AsyncSession, kind: AccountKind, user_id: int) -> list:
        id_col = getattr(kind.model, kind.id_column)
        stmt = select(kind.model).where(kind.model.user_id == user_id).order_by(id_col)
        return list(await db.scalars(stmt))

    async def find_histories(
        self, db: AsyncSession, kind: AccountKind, account_id: int, limit: int, offset: int
    ) -> list:
        model = kind.history_model
        stmt = (
            select(model)
            .where(getattr(model, kind.id_column) == account_id)
            .order_by(model.date.desc(), getattr(model, kind.history_id_column).desc())
            .limit(limit)
            .offset(offset)
        )
        return list(await db.scalars(stmt))

    async def save_history(self, db: AsyncSession, history):
        db.add(history)
        await db.flush()
        return history

    async def lock_checking_accounts(self, db: AsyncSession, ids: list[int]) -> list[CheckingAccount]:
        """돈이 움직이기 전 행 잠금 (docs/ERD.md 규칙 9). 잔액은 잠근 뒤에 읽은 값을 쓴다."""
        stmt = (
            select(CheckingAccount)
            .where(CheckingAccount.checking_account_id.in_(ids))
            .order_by(CheckingAccount.checking_account_id)  # 항상 같은 순서로 잠가 데드락 방지
            .with_for_update()
            # 세션에 이미 읽어 둔 객체가 있어도 잠근 시점의 최신 값으로 덮어쓴다
            .execution_options(populate_existing=True)
        )
        return list(await db.scalars(stmt))

    async def lock_account(self, db: AsyncSession, kind: AccountKind, account_id: int):
        """예금·적금 계좌 한 개를 잠근다 (규칙 9). lock_checking_accounts와 같은 이유로 populate_existing."""
        id_col = getattr(kind.model, kind.id_column)
        stmt = (
            select(kind.model).where(id_col == account_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        return await db.scalar(stmt)

    async def find_checking_by_account_num(self, db: AsyncSession, account_num: str) -> CheckingAccount | None:
        return await db.scalar(select(CheckingAccount).where(CheckingAccount.account_num == account_num))

    async def sum_today_transfer_amount(self, db: AsyncSession, checking_account_id: int, since) -> int:
        """since(오늘 00:00 KST를 UTC로 바꾼 값) 이후 이 계좌에서 나간 이체 합계 (1일 이체 한도 검사용).

        date 컬럼에 함수를 씌우지 않고 비교해야 (checking_account_id, date) 인덱스를 탄다.
        """
        stmt = select(func.coalesce(func.sum(CheckingAccountHistory.amount), 0)).where(
            CheckingAccountHistory.checking_account_id == checking_account_id,
            CheckingAccountHistory.type == TRANSFER_OUT,
            CheckingAccountHistory.date >= since,
        )
        return int(await db.scalar(stmt))  # PostgreSQL의 SUM(bigint)는 Decimal로 온다

    # 계좌번호 중복 검사 메서드는 두지 않는다. 앞자리로 종류가 나뉘므로 테이블 간 중복이 없고,
    # 같은 테이블 안의 중복은 unique 제약(IntegrityError)으로 잡아 service에서 재발급한다.


account_repository = AccountRepository()
