"""타행 송금 (보내는 쪽, SPEC 3절·6절).

순서: 비밀번호 → [트랜잭션] 출금 + PENDING 저장 → 허브 POST → 결과 반영.
출금을 되돌리는 것은 허브 응답 본문의 status가 FAILED일 때뿐이다. 그 밖(202, status 없는 4xx, 5xx, 타임아웃,
서명이 틀린 응답)은 결과를 모르는 상태라 PENDING으로 두고 worker.py가 확인한다 (이중 지급 방지).
허브 호출은 이 서비스 안에서만 한다 (LLM 도구로 주지 않는다, SPEC 6절).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import ApiException, BadRequestException, NotFoundException
from avengers_bank.domains.accounts.kinds import INTERBANK_OUT, INTERBANK_REFUND, KINDS
from avengers_bank.domains.accounts.models import CheckingAccount, CheckingAccountHistory
from avengers_bank.domains.accounts.password import check_account_password
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.accounts.service import account_service, require_open
from avengers_bank.domains.interbank.hub_client import HubReply, HubUnreachable, hub_call
from avengers_bank.domains.interbank.models import InterbankTransfer
from avengers_bank.domains.interbank.schemas import (
    BankInfo,
    InquiryRequest,
    InquiryResponse,
    InterbankResponse,
    InterbankSend,
)
from avengers_bank.domains.transfers.service import transfer_service
from avengers_bank.domains.users.models import User
from avengers_bank.domains.users.schemas import UserResponse


def require_enabled() -> None:
    if not get_settings().interbank_enabled:
        raise ApiException(503, "INTERBANK_DISABLED", "타행 이체를 사용할 수 없습니다.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _classify(reply: HubReply) -> str:
    """COMPLETED / FAILED / UNKNOWN. 서명이 틀리거나 5xx면 본문을 믿지 않고 UNKNOWN (SPEC 2.5, 3.3)."""
    if not reply.verified or reply.status >= 500:
        return "UNKNOWN"
    status = reply.body.get("status")
    if status == "COMPLETED" and reply.status == 200:
        return "COMPLETED"
    return "FAILED" if status == "FAILED" else "UNKNOWN"


class InterbankService:
    async def banks(self) -> list[BankInfo]:
        require_enabled()
        reply = await self._call("GET", "/v1/banks")
        own = get_settings().bank_code  # 자기 은행을 고르면 SAME_BANK로 거절된다 (SPEC 3.1)
        return [BankInfo(**b) for b in reply.body.get("banks", []) if b.get("bank_code") != own]

    async def inquiry(self, data: InquiryRequest) -> InquiryResponse:
        require_enabled()
        self._reject_own_bank(data.to_bank)
        reply = await self._call("POST", "/v1/inquiry", data.model_dump())
        name = reply.body.get("holder_name")
        if reply.status != 200 or not name:
            raise self._hub_error(reply)
        return InquiryResponse(**data.model_dump(), holder_name=name)

    async def send(self, db: AsyncSession, data: InterbankSend, user: UserResponse) -> InterbankResponse:
        require_enabled()
        self._reject_own_bank(data.to_bank)
        await check_account_password(db, KINDS["checking"], data.from_checking_account_id, data.account_password, user)
        bank_name = await self._bank_name(data.to_bank)
        transfer_id = str(uuid.uuid4())
        async with db.begin():  # 출금과 PENDING 저장은 한 트랜잭션 (SPEC 6절 3)
            await account_service.get_owned(db, KINDS["checking"], data.from_checking_account_id, user)
            (sender,) = await account_repository.lock_checking_accounts(db, [data.from_checking_account_id])
            require_open(sender)
            await transfer_service._check_limits(db, sender, data.amount)  # 잔액·1회·1일 한도
            sender.balance -= data.amount
            db.add(InterbankTransfer(
                transfer_id=transfer_id, direction="OUT", checking_account_id=sender.checking_account_id,
                peer_bank=data.to_bank, peer_bank_name=bank_name, peer_account=data.to_account,
                amount=data.amount, memo=data.memo, status="PENDING",
            ))
            await account_repository.save_history(db, CheckingAccountHistory(
                checking_account_id=sender.checking_account_id, amount=data.amount, balance_after=sender.balance,
                type=INTERBANK_OUT, counterpart_account=data.to_account, counterpart_name=bank_name,
            ))
        await self.deliver(db, transfer_id)
        row = await self._row(db, transfer_id)
        if row.status == "FAILED":
            code = row.fail_code or "RECEIVER_ERROR"
            raise ApiException(404 if code == "ACCOUNT_NOT_FOUND" else 400, code, row.fail_message or "이체에 실패했습니다.")
        return await self._response(db, row)

    async def status(self, db: AsyncSession, transfer_id: str, user: UserResponse) -> InterbankResponse:
        row = await self._row(db, transfer_id)
        if row is None or row.direction != "OUT":
            raise NotFoundException(code="TRANSFER_NOT_FOUND", message="이체를 찾을 수 없습니다.")
        async with db.begin():
            await account_service.get_owned(db, KINDS["checking"], row.checking_account_id, user)  # 남의 이체도 404
        return await self._response(db, row)

    async def deliver(self, db: AsyncSession, transfer_id: str) -> None:
        """허브에 POST하고 결과를 반영한다. 결과를 모르면 PENDING 그대로 둔다."""
        row, from_account, sender_name = await self._load(db, transfer_id)
        payload = {
            "transfer_id": transfer_id, "to_bank": row.peer_bank, "to_account": row.peer_account,
            "from_account": from_account, "amount": row.amount, "sender_name": sender_name, "memo": row.memo,
        }
        async with db.begin():
            await db.execute(update(InterbankTransfer).where(InterbankTransfer.transfer_id == transfer_id)
                             .values(last_sent_at=_now()))
        try:
            reply = await hub_call("POST", "/v1/transfers", payload)
        except HubUnreachable:
            return
        await self.apply(db, transfer_id, reply)

    async def apply(self, db: AsyncSession, transfer_id: str, reply: HubReply) -> None:
        """허브 응답(POST 또는 GET 결과)을 반영한다. 이미 끝난 거래면 아무것도 하지 않는다."""
        outcome = _classify(reply)
        if outcome == "UNKNOWN":
            return
        async with db.begin():
            row = (await db.execute(
                select(InterbankTransfer).where(InterbankTransfer.transfer_id == transfer_id).with_for_update()
            )).scalar_one()
            if row.status != "PENDING":
                return
            row.finished_at = _now()
            if outcome == "COMPLETED":
                row.status = "COMPLETED"
                row.peer_name = reply.body.get("holder_name") or row.peer_name
                return
            # FAILED: 출금을 되돌린다. 계좌 잠금은 행 잠금 뒤 (입금 쪽도 계좌만 잠그므로 순환이 없다)
            (account,) = await account_repository.lock_checking_accounts(db, [row.checking_account_id])
            account.balance += row.amount
            await account_repository.save_history(db, CheckingAccountHistory(
                checking_account_id=account.checking_account_id, amount=row.amount, balance_after=account.balance,
                type=INTERBANK_REFUND, counterpart_account=row.peer_account, counterpart_name=row.peer_bank_name,
            ))
            row.status = "FAILED"
            row.fail_code = (reply.body.get("error") or reply.body.get("fail_code") or "RECEIVER_ERROR")[:40]
            row.fail_message = (reply.body.get("message") or reply.body.get("fail_message") or "")[:200] or None

    # --- 내부 ---
    def _reject_own_bank(self, to_bank: str) -> None:
        if to_bank == get_settings().bank_code:
            raise BadRequestException(code="SAME_BANK", message="같은 은행 계좌로는 일반 이체를 이용해 주세요.")

    async def _call(self, method: str, path: str, payload: dict | None = None) -> HubReply:
        try:
            reply = await hub_call(method, path, payload)
        except HubUnreachable:
            raise ApiException(503, "HUB_UNAVAILABLE", "중계 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.") from None
        if not reply.verified:  # 서명이 틀린 응답은 믿지 않는다
            raise ApiException(502, "HUB_ERROR", "중계 서버 응답을 확인할 수 없습니다.")
        return reply

    def _hub_error(self, reply: HubReply) -> ApiException:
        code = reply.body.get("error") or "RECEIVER_ERROR"
        return ApiException(reply.status if 400 <= reply.status < 600 else 502, code,
                            reply.body.get("message") or "수취 조회에 실패했습니다.")

    async def _bank_name(self, code: str) -> str | None:
        try:  # 은행 이름은 표시용이라 못 얻어도 이체는 진행한다
            return next((b.name for b in await self.banks() if b.bank_code == code), None)
        except ApiException:
            return None

    async def _row(self, db: AsyncSession, transfer_id: str) -> InterbankTransfer | None:
        async with db.begin():
            return await db.get(InterbankTransfer, transfer_id, populate_existing=True)

    async def _load(self, db: AsyncSession, transfer_id: str) -> tuple[InterbankTransfer, str, str]:
        async with db.begin():
            row = await db.get(InterbankTransfer, transfer_id, populate_existing=True)
            account = await db.get(CheckingAccount, row.checking_account_id)
            user = await db.get(User, account.user_id)
            return row, account.account_num, user.name

    async def _response(self, db: AsyncSession, row: InterbankTransfer) -> InterbankResponse:
        async with db.begin():
            account = await db.get(CheckingAccount, row.checking_account_id, populate_existing=True)
        return InterbankResponse(
            transfer_id=row.transfer_id, status=row.status, to_bank=row.peer_bank, to_bank_name=row.peer_bank_name,
            to_account=row.peer_account, amount=row.amount, holder_name=row.peer_name,
            balance_after=account.balance, fail_code=row.fail_code, fail_message=row.fail_message,
        )


interbank_service = InterbankService()
