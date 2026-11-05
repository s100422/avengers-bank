import secrets
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.exceptions import (
    ApiException,
    BadRequestException,
    NotFoundException,
)
from avengers_bank.core.timezone import KST, today_kst
from avengers_bank.domains.accounts.interest import calc_interest
from avengers_bank.domains.accounts.kinds import (
    CLOSE_IN,
    CLOSE_OUT,
    INTEREST,
    KINDS,
    TRANSFER_IN,
    AccountKind,
)
from avengers_bank.domains.accounts.models import CheckingAccountHistory
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.accounts.schemas import (
    RESPONSES,
    AccountCloseRequest,
    AccountCloseResponse,
    AccountHistoryResponse,
    AccountSummaryResponse,
    AccountUpdate,
    CheckingAccountCreate,
    DepositAccountCreate,
    SavingsAccountCreate,
)
from avengers_bank.domains.products.service import product_service
from avengers_bank.domains.users.schemas import UserResponse

MAX_NUMBER_ATTEMPTS = 5


def _as_dict(kind: AccountKind, account) -> dict:
    """모델 컬럼을 응답용 dict로. 종류마다 다른 PK 이름은 account_id로 통일한다."""
    data = {c.name: getattr(account, c.name) for c in account.__table__.columns}
    data["account_id"] = data.pop(kind.id_column)
    return data


def to_response(kind: AccountKind, account):
    return RESPONSES[kind.name].model_validate(_as_dict(kind, account))


def _kst_date(moment: datetime):
    """저장된 UTC 시각의 KST 날짜. SQLite는 시간대 없이 돌려줘서 UTC로 본다."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(KST).date()


class AccountService:
    async def open_checking(self, db: AsyncSession, data: CheckingAccountCreate, user: UserResponse):
        return await self._open(
            db, KINDS["checking"], user, data.product_id,
            nickname=data.nickname,
            per_transfer_limit=data.per_transfer_limit,
            daily_transfer_limit=data.daily_transfer_limit,
        )

    async def open_deposit(self, db: AsyncSession, data: DepositAccountCreate, user: UserResponse):
        return await self._open(
            db, KINDS["deposit"], user, data.product_id,
            nickname=data.nickname, maturity_date=data.maturity_date,
        )

    async def open_savings(self, db: AsyncSession, data: SavingsAccountCreate, user: UserResponse):
        return await self._open(
            db, KINDS["savings"], user, data.product_id,
            nickname=data.nickname, maturity_date=data.maturity_date,
            monthly_payment=data.monthly_payment, monthly_deposit_date=data.monthly_deposit_date,
        )

    async def _open(self, db: AsyncSession, kind: AccountKind, user: UserResponse, product_id: int, **fields):
        # 같은 테이블 안에서 번호가 겹치면 unique 제약(IntegrityError)이 막는다. 새 번호로 다시 시도한다.
        for _ in range(MAX_NUMBER_ATTEMPTS):
            try:
                async with db.begin():
                    await product_service.require_account_product(db, product_id, kind.product_type)
                    account = kind.model(
                        user_id=user.user_id, product_id=product_id,
                        account_num=self._new_account_num(kind), **fields,
                    )
                    await account_repository.save(db, account)
                    await db.refresh(account)
                return to_response(kind, account)
            except IntegrityError as e:
                if "account_num" not in str(e.orig):
                    raise
        raise ApiException(
            500, "ACCOUNT_NUMBER_GENERATION_FAILED", "계좌번호를 발급하지 못했습니다. 다시 시도해 주세요."
        )

    def _new_account_num(self, kind: AccountKind) -> str:
        return f"{kind.prefix}-{secrets.randbelow(1000):03d}-{secrets.randbelow(1_000_000):06d}"

    async def get_my_accounts(self, db: AsyncSession, user: UserResponse) -> list[AccountSummaryResponse]:
        summaries = []
        for kind in KINDS.values():
            for account in await account_repository.find_by_user_id(db, kind, user.user_id):
                summaries.append(
                    AccountSummaryResponse(account_type=kind.name, **_as_dict(kind, account))
                )
        return sorted(summaries, key=lambda s: s.created_at)

    async def get_account(self, db: AsyncSession, type: str, account_id: int, user: UserResponse):
        kind = KINDS[type]
        return to_response(kind, await self.get_owned(db, kind, account_id, user))

    async def get_histories(
        self, db: AsyncSession, type: str, account_id: int, user: UserResponse, limit: int, offset: int
    ) -> list[AccountHistoryResponse]:
        kind = KINDS[type]
        await self.get_owned(db, kind, account_id, user)
        histories = await account_repository.find_histories(db, kind, account_id, limit, offset)
        return [AccountHistoryResponse.model_validate(h) for h in histories]

    async def update_account(
        self, db: AsyncSession, type: str, account_id: int, data: AccountUpdate, user: UserResponse
    ):
        kind = KINDS[type]
        changes = data.model_dump(exclude_unset=True)
        # 한도에 null을 보내면 "안 바꿈"으로 본다 (nickname만 null이 "지우기")
        limits = {k: changes.pop(k) for k in ("per_transfer_limit", "daily_transfer_limit") if k in changes}
        limits = {k: v for k, v in limits.items() if v is not None}

        async with db.begin():
            account = await self.get_owned(db, kind, account_id, user)
            if limits:
                if kind.name != "checking":
                    raise BadRequestException(
                        code="TRANSFER_LIMIT_NOT_SUPPORTED", message="이체 한도는 입출금 계좌만 바꿀 수 있습니다."
                    )
                per = limits.get("per_transfer_limit", account.per_transfer_limit)
                daily = limits.get("daily_transfer_limit", account.daily_transfer_limit)
                if per > daily:
                    raise BadRequestException(
                        code="INVALID_TRANSFER_LIMIT", message="1회 이체 한도는 1일 이체 한도보다 클 수 없습니다."
                    )
            for field, value in {**changes, **limits}.items():
                setattr(account, field, value)
        return to_response(kind, account)

    async def close_account(
        self, db: AsyncSession, type: str, account_id: int, data: AccountCloseRequest, user: UserResponse
    ) -> AccountCloseResponse:
        """예금·적금 해지: 원금+이자를 내 입출금 계좌로 보낸다 (C-043). 잠금 순서는 입출금 → 예금·적금."""
        kind = KINDS[type]
        if kind.name == "checking":
            raise BadRequestException(code="CLOSE_NOT_SUPPORTED", message="예금·적금만 해지할 수 있습니다.")
        async with db.begin():
            await self.get_owned(db, kind, account_id, user)
            await self.get_owned(db, KINDS["checking"], data.to_checking_account_id, user)

            (checking,) = await account_repository.lock_checking_accounts(db, [data.to_checking_account_id])
            account = await account_repository.lock_account(db, kind, account_id)
            if account.status == "CLOSED":  # 잠근 뒤에 확인해야 동시에 두 번 눌러도 한 번만 해지된다
                raise BadRequestException(code="ACCOUNT_CLOSED", message="이미 해지된 계좌입니다.")

            today = today_kst()
            product = await product_service.get_account_product(db, account.product_id)
            deposits = [
                (_kst_date(h.date), h.amount)
                for h in await account_repository.find_histories_by_type(db, kind, account_id, TRANSFER_IN)
            ]
            interest = calc_interest(deposits, product.interest_rate, today, account.maturity_date)
            principal = account.balance
            total = principal + interest

            if interest > 0:
                await account_repository.save_history(db, kind.history_model(
                    **{kind.id_column: account_id}, amount=interest, balance_after=total, type=INTEREST,
                ))
            if total > 0:
                await account_repository.save_history(db, kind.history_model(
                    **{kind.id_column: account_id}, amount=total, balance_after=0, type=CLOSE_OUT,
                    counterpart_account=checking.account_num,
                ))
                checking.balance += total
                await account_repository.save_history(db, CheckingAccountHistory(
                    checking_account_id=checking.checking_account_id, amount=total,
                    balance_after=checking.balance, type=CLOSE_IN, counterpart_account=account.account_num,
                ))
            account.balance = 0
            account.status = "CLOSED"
            account.closed_at = datetime.now(timezone.utc)

        return AccountCloseResponse(
            account_type=kind.name, account_id=account_id, principal=principal, interest=interest,
            total_amount=total, early_close=today < account.maturity_date, closed_at=account.closed_at,
            to_account_num=checking.account_num, to_balance_after=checking.balance,
        )

    async def get_owned(self, db: AsyncSession, kind: AccountKind, account_id: int, user: UserResponse):
        account = await account_repository.find_by_id(db, kind, account_id)
        # 남의 계좌도 404로 알려서 ID가 존재하는지 드러나지 않게 한다 (C-031)
        if account is None or account.user_id != user.user_id:
            raise NotFoundException(code="ACCOUNT_NOT_FOUND", message="계좌를 찾을 수 없습니다.")
        return account


account_service = AccountService()
