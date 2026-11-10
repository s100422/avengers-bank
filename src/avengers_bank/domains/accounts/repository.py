from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.timezone import kst_start_utc
from avengers_bank.domains.accounts.kinds import INTERBANK_OUT, TRANSFER_OUT, AccountKind
from avengers_bank.domains.accounts.models import AccountNotification, CheckingAccount, CheckingAccountHistory
from avengers_bank.domains.accounts.schemas import HistoryFilter


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
        self, db: AsyncSession, kind: AccountKind, account_id: int, limit: int, offset: int,
        f: HistoryFilter | None = None,
    ) -> list:
        model = kind.history_model
        conditions = [getattr(model, kind.id_column) == account_id]
        if f:
            # 날짜는 KST 기준 하루 단위: date_from 00:00 이상, date_to 다음 날 00:00 미만
            if f.date_from:
                conditions.append(model.date >= kst_start_utc(f.date_from))
            if f.date_to:
                conditions.append(model.date < kst_start_utc(f.date_to + timedelta(days=1)))
            if f.types:
                conditions.append(model.type.in_(f.types))
            if f.min_amount is not None:
                conditions.append(model.amount >= f.min_amount)
            if f.max_amount is not None:
                conditions.append(model.amount <= f.max_amount)
            if f.q:
                # 상대 이름(사용처 등)은 입출금 내역에만 있다. autoescape: 입력의 % _를 글자 그대로 찾는다
                columns = [model.counterpart_account] + ([model.counterpart_name] if hasattr(model, "counterpart_name") else [])
                conditions.append(or_(*(c.icontains(f.q, autoescape=True) for c in columns)))
        stmt = (
            select(model)
            .where(*conditions)
            .order_by(model.date.desc(), getattr(model, kind.history_id_column).desc())
            .limit(limit)
            .offset(offset)
        )
        return list(await db.scalars(stmt))

    async def find_histories_by_type(self, db: AsyncSession, kind: AccountKind, account_id: int, type: str) -> list:
        model = kind.history_model
        stmt = select(model).where(getattr(model, kind.id_column) == account_id, model.type == type)
        return list(await db.scalars(stmt))

    async def save_history(self, db: AsyncSession, history):
        db.add(history)
        await db.flush()
        if isinstance(history, CheckingAccountHistory):
            account = await db.get(CheckingAccount, history.checking_account_id)
            db.add(AccountNotification(
                user_id=account.user_id,
                checking_account_history_id=history.checking_account_history_id,
            ))
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
        """계좌번호로 찾는다(남이 보내는 이체의 받는 계좌). 탈퇴로 닫힌 계좌는 없는 계좌로 본다.
        잠그기 전 조회라 참고용이다: 이체는 잠근 뒤 require_open으로 다시 확인한다(그사이 탈퇴할 수 있다)."""
        return await db.scalar(
            select(CheckingAccount).where(CheckingAccount.account_num == account_num, CheckingAccount.closed_at.is_(None))
        )

    async def lock_checking_by_account_num(self, db: AsyncSession, account_num: str) -> CheckingAccount | None:
        """계정 복구가 계좌 비밀번호를 검증하기 전에 그 행을 잠근다 (lock_account와 같은 이유: 실패 횟수 직렬화).
        탈퇴로 닫힌 계좌는 없는 계좌로 본다: 탈퇴 회원의 아이디·비밀번호 찾기가 없는 계좌와 같은 응답이 된다."""
        stmt = (
            select(CheckingAccount).where(CheckingAccount.account_num == account_num, CheckingAccount.closed_at.is_(None))
            .with_for_update().execution_options(populate_existing=True)
        )
        return await db.scalar(stmt)

    async def sum_today_transfer_amount(self, db: AsyncSession, checking_account_id: int, since) -> int:
        """since(오늘 00:00 KST를 UTC로 바꾼 값) 이후 이 계좌에서 나간 이체 합계 (1일 이체 한도 검사용).

        date 컬럼에 함수를 씌우지 않고 비교해야 (checking_account_id, date) 인덱스를 탄다.
        """
        stmt = select(func.coalesce(func.sum(CheckingAccountHistory.amount), 0)).where(
            CheckingAccountHistory.checking_account_id == checking_account_id,
            CheckingAccountHistory.type.in_([TRANSFER_OUT, INTERBANK_OUT]),  # 타행 이체도 1일 한도에 센다
            CheckingAccountHistory.date >= since,
        )
        return int(await db.scalar(stmt))  # PostgreSQL의 SUM(bigint)는 Decimal로 온다

    # 계좌번호 중복 검사 메서드는 두지 않는다. 앞자리로 종류가 나뉘므로 테이블 간 중복이 없고,
    # 같은 테이블 안의 중복은 unique 제약(IntegrityError)으로 잡아 service에서 재발급한다.


account_repository = AccountRepository()
