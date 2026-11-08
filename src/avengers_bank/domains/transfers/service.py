from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.exceptions import BadRequestException, NotFoundException
from avengers_bank.core.timezone import today_kst, today_start_utc
from avengers_bank.domains.accounts.kinds import (
    KINDS,
    TO_DEPOSIT,
    TO_SAVINGS,
    TRANSFER_IN,
    TRANSFER_OUT,
    AccountKind,
)
from avengers_bank.domains.accounts.models import CheckingAccount, CheckingAccountHistory
from avengers_bank.domains.accounts.password import check_account_password
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.accounts.service import account_service
from avengers_bank.domains.transfers.schemas import (
    SavingsPaymentCreate,
    TransferCreate,
    TransferResponse,
    TransferTarget,
)
from avengers_bank.domains.users.models import User
from avengers_bank.domains.users.schemas import UserResponse


def _require_funds(sender: CheckingAccount, amount: int) -> None:
    if sender.balance < amount:
        raise BadRequestException(code="INSUFFICIENT_BALANCE", message="잔액이 부족합니다.")


class TransferService:
    # 잠금 규칙은 docs/ERD.md 규칙 9: 돈을 바꾸기 전에 잠그고, 잠근 뒤에 검사한다.
    # 잠금 순서: 입출금 계좌(ID 오름차순) → 예금·적금 계좌.

    async def transfer(self, db: AsyncSession, data: TransferCreate, user: UserResponse) -> TransferResponse:
        """입출금 → 입출금 이체. 잔액, 1회 한도, 1일 한도를 검사한다."""
        # 보내는 계좌의 비밀번호를 먼저 따로 확인·커밋한다 (틀린 횟수가 롤백되지 않게, password.py)
        await check_account_password(db, KINDS["checking"], data.from_checking_account_id, data.account_password, user)
        async with db.begin():
            return await self.transfer_in_tx(db, data, user)

    async def transfer_in_tx(self, db: AsyncSession, data: TransferTarget, user: UserResponse) -> TransferResponse:
        """transfer와 같지만 호출한 쪽이 연 트랜잭션 안에서 실행한다 (AI 이체 초안 확인, C-070).
        계좌 비밀번호는 검사하지 않는다: 호출한 쪽이 트랜잭션을 열기 전에 check_account_password로 확인해야 한다."""
        sender, receiver = await self._parties(db, data, user)

        # 두 계좌를 ID 순서대로 한 번에 잠근다 (A→B와 B→A가 동시에 와도 데드락이 없다)
        ids = [sender.checking_account_id, receiver.checking_account_id]
        locked = {a.checking_account_id: a for a in await account_repository.lock_checking_accounts(db, ids)}
        sender, receiver = locked[ids[0]], locked[ids[1]]

        # 잠근 뒤에 검사한다. 1일 합계도 보내는 계좌를 잠근 뒤에 계산해야 동시 이체가 한도를 못 넘는다
        await self._check_limits(db, sender, data.amount)

        sender.balance -= data.amount
        receiver.balance += data.amount
        # 거래 내역에 상대 실명을 남긴다: 보낸 쪽에는 받는 분, 받은 쪽에는 보낸 분 (C-065)
        receiver_name = (await db.get(User, receiver.user_id)).name
        sender_name = (await db.get(User, sender.user_id)).name
        await self._save_checking_history(db, sender, TRANSFER_OUT, data.amount, receiver.account_num, receiver_name)
        await self._save_checking_history(db, receiver, TRANSFER_IN, data.amount, sender.account_num, sender_name)

        return TransferResponse(
            from_account_num=sender.account_num, to_account_num=receiver.account_num,
            amount=data.amount, balance_after=sender.balance,
        )

    async def preview(
        self, db: AsyncSession, data: TransferTarget, user: UserResponse
    ) -> tuple[CheckingAccount, CheckingAccount, str]:
        """이체와 같은 검사만 하고 돈은 옮기지 않는다 (AI 이체 초안, C-070). (보내는 계좌, 받는 계좌, 받는 분 실명).

        잠그지 않으므로 결과는 참고용이다. 실제 실행(transfer_in_tx)이 잠근 뒤에 다시 검사한다.
        """
        async with db.begin():
            sender, receiver = await self._parties(db, data, user)
            await self._check_limits(db, sender, data.amount)
            receiver_name = (await db.get(User, receiver.user_id)).name
        return sender, receiver, receiver_name

    async def _parties(
        self, db: AsyncSession, data: TransferTarget, user: UserResponse
    ) -> tuple[CheckingAccount, CheckingAccount]:
        # 불변 정보(소유자, 받는 계좌, 같은 계좌 여부)는 잠그기 전에 확인한다
        sender = await account_service.get_owned(db, KINDS["checking"], data.from_checking_account_id, user)
        receiver = await account_repository.find_checking_by_account_num(db, data.to_account_num)
        if receiver is None:
            raise NotFoundException(code="ACCOUNT_NOT_FOUND", message="받는 계좌를 찾을 수 없습니다.")
        if receiver.checking_account_id == sender.checking_account_id:
            raise BadRequestException(
                code="SAME_ACCOUNT_TRANSFER", message="같은 계좌로는 이체할 수 없습니다."
            )
        return sender, receiver

    async def _check_limits(self, db: AsyncSession, sender: CheckingAccount, amount: int) -> None:
        _require_funds(sender, amount)
        if amount > sender.per_transfer_limit:
            raise BadRequestException(
                code="PER_TRANSFER_LIMIT_EXCEEDED", message="1회 이체 한도를 초과했습니다."
            )
        used_today = await account_repository.sum_today_transfer_amount(
            db, sender.checking_account_id, today_start_utc()
        )
        if used_today + amount > sender.daily_transfer_limit:
            raise BadRequestException(
                code="DAILY_LIMIT_EXCEEDED", message="1일 이체 한도를 초과했습니다."
            )

    async def pay_savings(self, db: AsyncSession, data: SavingsPaymentCreate, user: UserResponse) -> TransferResponse:
        """입출금 → 내 적금 납입."""
        await check_account_password(db, KINDS["checking"], data.from_checking_account_id, data.account_password, user)
        return await self._pay(
            db, user, data.from_checking_account_id, KINDS["savings"], data.savings_account_id, data.amount, TO_SAVINGS
        )

    async def _pay(
        self, db: AsyncSession, user: UserResponse, from_id: int, to_kind: AccountKind,
        to_id: int, amount: int, out_type: str,
    ) -> TransferResponse:
        async with db.begin():
            return await self._pay_in_tx(db, user, from_id, to_kind, to_id, amount, out_type)

    async def pay_deposit_in_tx(
        self, db: AsyncSession, user: UserResponse, from_id: int, deposit_id: int, amount: int
    ) -> TransferResponse:
        """예금 가입 금액 입금. 호출한 쪽이 연 트랜잭션 안에서 실행한다 (가입 후 추가 입금은 없다).
        출금 계좌 비밀번호는 호출한 쪽(account_service.open_deposit)이 트랜잭션 전에 확인한다."""
        return await self._pay_in_tx(db, user, from_id, KINDS["deposit"], deposit_id, amount, TO_DEPOSIT)

    async def _pay_in_tx(
        self, db: AsyncSession, user: UserResponse, from_id: int, to_kind: AccountKind,
        to_id: int, amount: int, out_type: str,
    ) -> TransferResponse:
        # 적금·예금은 본인 계좌에만 넣을 수 있다. 1회·1일 이체 한도는 입출금→입출금 이체에만 적용한다.
        await account_service.get_owned(db, KINDS["checking"], from_id, user)
        target = await account_service.get_owned(db, to_kind, to_id, user)
        # 만기일은 바뀌지 않는 정보라 잠그기 전에 확인한다. 만기일 당일부터 거절한다 (C-033)
        if target.maturity_date <= today_kst():
            raise BadRequestException(code="ACCOUNT_MATURED", message="만기가 지난 계좌에는 입금할 수 없습니다.")

        (sender,) = await account_repository.lock_checking_accounts(db, [from_id])  # 입출금 먼저
        target = await account_repository.lock_account(db, to_kind, to_id)  # 그다음 예금·적금
        if target.status == "CLOSED":  # 잠근 뒤에 확인해야 해지와 동시에 와도 해지된 계좌에 돈이 남지 않는다
            raise BadRequestException(code="ACCOUNT_CLOSED", message="해지된 계좌에는 입금할 수 없습니다.")

        _require_funds(sender, amount)
        sender.balance -= amount
        target.balance += amount
        await self._save_checking_history(db, sender, out_type, amount, target.account_num)
        await account_repository.save_history(
            db,
            to_kind.history_model(
                **{to_kind.id_column: to_id}, amount=amount, balance_after=target.balance,
                type=TRANSFER_IN, counterpart_account=sender.account_num,
            ),
        )

        return TransferResponse(
            from_account_num=sender.account_num, to_account_num=target.account_num,
            amount=amount, balance_after=sender.balance,
        )

    async def _save_checking_history(
        self, db: AsyncSession, account: CheckingAccount, type: str, amount: int, counterpart: str,
        counterpart_name: str | None = None,
    ) -> None:
        await account_repository.save_history(
            db,
            CheckingAccountHistory(
                checking_account_id=account.checking_account_id, amount=amount,
                balance_after=account.balance, type=type, counterpart_account=counterpart,
                counterpart_name=counterpart_name,
            ),
        )


transfer_service = TransferService()
