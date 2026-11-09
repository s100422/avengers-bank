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
from avengers_bank.domains.accounts.interest import EARLY_CLOSE_RATE_FACTOR, calc_interest, scheduled_payment_days
from avengers_bank.domains.accounts.kinds import (
    CLOSE_IN,
    CLOSE_OUT,
    INTEREST,
    KINDS,
    TRANSFER_IN,
    AccountKind,
)
from avengers_bank.domains.accounts.models import CheckingAccountHistory
from avengers_bank.domains.accounts.password import check_account_password, set_account_password
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
    HistoryFilter,
    InterestPreviewResponse,
    SavingsAccountCreate,
)
from avengers_bank.domains.products.service import product_service
from avengers_bank.domains.terms import service as terms_service
from avengers_bank.domains.terms.schemas import TermsConsentIn
from avengers_bank.domains.users.schemas import UserResponse

MAX_NUMBER_ATTEMPTS = 5
# 응답 dict에 절대 싣지 않는 컬럼 (응답 스키마에 없어도 실수로 추가되는 일을 막으려고 여기서 뺀다)
SECRET_COLUMNS = {"password_hash", "password_failed_count", "password_locked_at"}


def _as_dict(kind: AccountKind, account) -> dict:
    """모델 컬럼을 응답용 dict로. 종류마다 다른 PK 이름은 account_id로 통일한다."""
    data = {c.name: getattr(account, c.name) for c in account.__table__.columns if c.name not in SECRET_COLUMNS}
    data["account_id"] = data.pop(kind.id_column)
    # 화면 안내용 상태만 bool로 내보낸다 (해시·실패 횟수는 내보내지 않는다)
    data["password_set"] = account.password_hash is not None
    data["password_locked"] = account.password_locked_at is not None
    return data


def to_response(kind: AccountKind, account):
    return RESPONSES[kind.name].model_validate(_as_dict(kind, account))


def require_open(account, message: str = "계좌를 찾을 수 없습니다.") -> None:
    """탈퇴로 닫힌 입출금 계좌(closed_at)는 없는 계좌처럼 404. 잔액을 바꾸는 곳에서 **행을 잠근 뒤** 부른다:
    탈퇴는 같은 행을 잠그고 '잔액 0 확인 → closed_at'을 하므로, 잠근 뒤 확인하면 '탈퇴했는데 돈이 들어옴'이 없다."""
    if account.closed_at is not None:
        raise NotFoundException(code="ACCOUNT_NOT_FOUND", message=message)


def _kst_date(moment: datetime):
    """저장된 UTC 시각의 KST 날짜. SQLite는 시간대 없이 돌려줘서 UTC로 본다."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(KST).date()


class AccountService:
    async def open_checking(self, db: AsyncSession, data: CheckingAccountCreate, user: UserResponse):
        return await self._open(
            db, KINDS["checking"], user, data.product_id, data.terms, data.account_password,
            nickname=data.nickname,
            per_transfer_limit=data.per_transfer_limit,
            daily_transfer_limit=data.daily_transfer_limit,
        )

    async def open_deposit(
        self, db: AsyncSession, data: DepositAccountCreate, user: UserResponse, after_open=None
    ):
        """after_open(db, account): 개설과 같은 트랜잭션 안에서 호출된다 (가입 금액 입금용)."""
        inner = after_open

        async def checked_after_open(db, account):
            # 돈을 옮기기 전에 상품별 최소 가입 금액을 확인한다 (실패하면 개설 전체 롤백)
            product = await product_service.get_account_product(db, data.product_id)
            if data.initial_amount is not None and product.min_amount and data.initial_amount < product.min_amount:
                raise BadRequestException(
                    code="BELOW_MIN_AMOUNT",
                    message=f"이 상품의 최소 가입 금액은 {product.min_amount:,}원입니다.",
                )
            if inner:
                await inner(db, account)

        # 가입 금액이 나가는 입출금 계좌의 비밀번호를 먼저 확인한다 (실패 횟수는 따로 커밋, password.py)
        await check_account_password(
            db, KINDS["checking"], data.from_checking_account_id, data.from_account_password, user
        )
        return await self._open(
            db, KINDS["deposit"], user, data.product_id, data.terms, data.account_password,
            after_open=checked_after_open,
            nickname=data.nickname, maturity_date=data.maturity_date,
        )

    async def open_savings(self, db: AsyncSession, data: SavingsAccountCreate, user: UserResponse):
        return await self._open(
            db, KINDS["savings"], user, data.product_id, data.terms, data.account_password,
            nickname=data.nickname, maturity_date=data.maturity_date,
            monthly_payment=data.monthly_payment, monthly_deposit_date=data.monthly_deposit_date,
        )

    async def _open(
        self, db: AsyncSession, kind: AccountKind, user: UserResponse, product_id: int, terms: TermsConsentIn,
        password: str, after_open=None, **fields,
    ):
        # 같은 테이블 안에서 번호가 겹치면 unique 제약(IntegrityError)이 막는다. 새 번호로 다시 시도한다.
        for _ in range(MAX_NUMBER_ATTEMPTS):
            try:
                async with db.begin():
                    await product_service.require_account_product(db, product_id, kind.product_type)
                    # 약관 동의 검증·기록은 개설과 같은 트랜잭션: 한쪽이 실패하면 둘 다 롤백된다 (C-075)
                    current, agreed = await terms_service.check_consent(db, kind.name, product_id, terms)
                    account = kind.model(
                        user_id=user.user_id, product_id=product_id,
                        account_num=self._new_account_num(kind), **fields,
                    )
                    await set_account_password(db, account, password)
                    await account_repository.save(db, account)
                    await terms_service.record_consent(
                        db, user, kind.name, getattr(account, kind.id_column), current, agreed
                    )
                    if after_open:
                        await after_open(db, account)
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
        self, db: AsyncSession, type: str, account_id: int, user: UserResponse, limit: int, offset: int,
        f: HistoryFilter | None = None,
    ) -> list[AccountHistoryResponse]:
        kind = KINDS[type]
        await self.get_owned(db, kind, account_id, user)
        histories = await account_repository.find_histories(db, kind, account_id, limit, offset, f)
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
        # 해지하는 예금·적금 계좌의 비밀번호. 이 짧은 트랜잭션은 그 계좌만 잠그고 커밋한다 (password.py)
        await check_account_password(db, kind, account_id, data.account_password, user)
        async with db.begin():
            await self.get_owned(db, kind, account_id, user)
            await self.get_owned(db, KINDS["checking"], data.to_checking_account_id, user)

            (checking,) = await account_repository.lock_checking_accounts(db, [data.to_checking_account_id])
            require_open(checking)
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

    async def interest_preview(
        self, db: AsyncSession, type: str, account_id: int, user: UserResponse
    ) -> InterestPreviewResponse:
        """예금·적금의 이자 미리 보기: 오늘 해지하면 / 만기까지 두면 (C-104). 읽기만 한다.
        계산은 해지(close_account)와 같은 calc_interest를 쓰므로 오늘 해지 값은 실제 해지 결과와 같다."""
        kind = KINDS[type]
        if kind.name == "checking":
            raise BadRequestException(code="INTEREST_NOT_SUPPORTED", message="예금·적금만 이자를 미리 볼 수 있습니다.")
        account = await self.get_owned(db, kind, account_id, user)
        if account.status == "CLOSED":
            raise BadRequestException(code="ACCOUNT_CLOSED", message="이미 해지된 계좌입니다.")
        today = today_kst()
        product = await product_service.get_account_product(db, account.product_id)
        deposits = [
            (_kst_date(h.date), h.amount)
            for h in await account_repository.find_histories_by_type(db, kind, account_id, TRANSFER_IN)
        ]
        rate, maturity, principal = product.interest_rate, account.maturity_date, account.balance
        today_interest = calc_interest(deposits, rate, today, maturity)

        monthly = getattr(account, "monthly_payment", None)  # 적금만
        future_days = scheduled_payment_days(today, maturity, account.monthly_deposit_date) if monthly else []
        projected = deposits + [(day, monthly) for day in future_days]
        maturity_principal = principal + (monthly or 0) * len(future_days)
        maturity_interest = calc_interest(projected, rate, maturity, maturity)
        return InterestPreviewResponse(
            account_type=kind.name, interest_rate=f"{rate.normalize():f}", maturity_date=maturity,
            close_today_principal=principal, close_today_interest=today_interest,
            close_today_total=principal + today_interest,
            close_today_rate=f"{(rate * EARLY_CLOSE_RATE_FACTOR if today < maturity else rate).normalize():f}",
            close_today_early=today < maturity,
            maturity_principal=maturity_principal, maturity_interest=maturity_interest,
            maturity_total=maturity_principal + maturity_interest,
            assumed_payments=len(future_days), monthly_payment=monthly,
        )

    async def get_owned(self, db: AsyncSession, kind: AccountKind, account_id: int, user: UserResponse):
        account = await account_repository.find_by_id(db, kind, account_id)
        # 남의 계좌도 404로 알려서 ID가 존재하는지 드러나지 않게 한다 (C-031)
        if account is None or account.user_id != user.user_id:
            raise NotFoundException(code="ACCOUNT_NOT_FOUND", message="계좌를 찾을 수 없습니다.")
        return account


account_service = AccountService()
