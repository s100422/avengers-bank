import re
import secrets
from datetime import datetime, timedelta, timezone

from pydantic import Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import ApiException, BadRequestException, NotFoundException
from avengers_bank.domains.accounts.kinds import KINDS
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.accounts.schemas import Amount
from avengers_bank.domains.accounts.service import account_service, require_open
from avengers_bank.domains.interbank.schemas import BankInfo, InquiryRequest
from avengers_bank.domains.interbank.service import interbank_service
from avengers_bank.domains.transfers.limits import check_transfer_limits
from avengers_bank.domains.agent.models import TransferDraft
from avengers_bank.domains.agent.schemas import TransferAction
from avengers_bank.domains.agent.tools.common import ToolArgs, account_name, mask_num
from avengers_bank.domains.transfers.schemas import TransferTarget
from avengers_bank.domains.transfers.service import transfer_service
from avengers_bank.domains.users.schemas import UserResponse

DRAFT_TTL = timedelta(minutes=5)


class PrepareTransferArgs(ToolArgs):
    from_account: str = Field(
        min_length=1, max_length=50,
        description="출금할 내 입출금 계좌. 사용자가 말한 이름(별칭·상품명) 또는 번호 끝 4자리 그대로 (예: '월급', '생활비 통장', '6991')")
    to_account: str | None = Field(
        default=None, min_length=1, max_length=50,
        description="받는 계좌가 사용자 본인의 입출금 계좌일 때 그 이름 또는 번호 끝 4자리. to_account_num과 둘 중 하나만 쓴다")
    to_account_num: str | None = Field(
        default=None, min_length=1, max_length=50,
        description="받는 계좌가 다른 사람 계좌일 때 사용자가 알려 준 계좌번호 전체. to_account와 둘 중 하나만 쓴다")
    to_bank: str | None = Field(
        default=None, min_length=1, max_length=30,
        description="받는 계좌가 다른 은행이면 사용자가 말한 은행 이름 또는 3자리 은행 코드 그대로 (예: '가짜은행', '902'). "
                    "우리 은행(SpiderBank) 계좌면 비운다. to_account_num과 같이 쓴다")
    amount: Amount = Field(description="이체 금액(원, 양의 정수)")

    @model_validator(mode="after")
    def _exactly_one_target(self):
        if (self.to_account is None) == (self.to_account_num is None):
            raise ValueError("to_account(내 계좌)와 to_account_num(다른 사람 계좌) 중 하나만 넣어야 합니다.")
        if self.to_bank is not None and self.to_account_num is None:
            raise ValueError("to_bank(다른 은행)는 to_account_num(계좌번호 전체)과 같이 넣어야 합니다.")
        return self


def name_key(text: str) -> str:
    """'월급 계좌'와 '월급 통장'이 같게 읽히도록 공백과 '계좌·통장'을 뺀다."""
    return re.sub(r"계좌|통장", "", re.sub(r"\s+", "", text))


async def find_own_checking(db: AsyncSession, user: UserResponse, ref: str, role: str) -> tuple[int, str, str]:
    """사용자가 말한 이름·번호 끝자리로 내 입출금 계좌 하나를 찾는다 → (account_id, 전체 번호, 이름).
    없거나 여럿이면 후보(이름·마스킹된 번호, id 없음)를 오류로 돌려 모델이 사용자에게 되묻게 한다."""
    try:
        names: dict[int, str] = {}
        own = [
            (a.checking_account_id, a.account_num, await account_name(db, a, names))
            for a in await account_repository.find_by_user_id(db, KINDS["checking"], user.user_id)
        ]
    finally:
        await db.rollback()  # 위 조회가 연 트랜잭션을 닫아야 preview의 db.begin()이 동작한다
    key, digits = name_key(ref), re.sub(r"\D", "", ref)
    tiers = [  # 앞 단계에서 하나라도 찾으면 뒤 단계는 보지 않는다
        [a for a in own if key and name_key(a[2]) == key],
        [a for a in own if key and (key in name_key(a[2]) or name_key(a[2]) in key)],
        [a for a in own if len(digits) >= 4 and a[1].replace("-", "").endswith(digits)],
    ]
    found = next((t for t in tiers if t), [])
    if len(found) == 1:
        return found[0]
    candidates = ", ".join(f"{a[2]}({mask_num(a[1])})" for a in own) or "없음"
    if not found:
        raise NotFoundException(
            code=f"{role}_ACCOUNT_NOT_FOUND",
            message=f"'{ref}'에 해당하는 내 입출금 계좌가 없습니다. 내 입출금 계좌: {candidates}. 사용자에게 어느 계좌인지 물어보세요.",
        )
    raise BadRequestException(
        code="ACCOUNT_AMBIGUOUS",
        message=f"'{ref}'에 해당하는 계좌가 여러 개입니다: {', '.join(f'{a[2]}({mask_num(a[1])})' for a in found)}. 사용자에게 어느 계좌인지 물어보세요.",
    )


def bank_key(text: str) -> str:
    """'KB국민은행'과 '국민 은행'이 같게 읽히도록 공백·'은행'을 빼고 소문자로."""
    return re.sub(r"\s+|은행", "", text).lower()


async def find_other_bank(ref: str) -> BankInfo | None:
    """사용자가 말한 은행 이름·코드로 허브 참가 은행 하나를 찾는다. 우리 은행이면 None(당행 이체).
    없거나 여럿이면 후보를 오류로 돌려 모델이 되묻게 한다. 은행 목록 조회만 하고 돈을 움직이는 허브 호출은 하지 않는다."""
    settings = get_settings()
    key = bank_key(ref)
    if ref.strip() == settings.bank_code or (key and key in (bank_key(settings.bank_name), "스파이더뱅크", "spiderbank")):
        return None
    banks = await interbank_service.banks()
    tiers = [  # 앞 단계에서 하나라도 찾으면 뒤 단계는 보지 않는다
        [b for b in banks if ref.strip() == b.bank_code],
        [b for b in banks if key and key == bank_key(b.name)],
        [b for b in banks if key and (key in bank_key(b.name) or bank_key(b.name) in key)],
    ]
    found = next((t for t in tiers if t), [])
    if len(found) == 1:
        return found[0]
    candidates = ", ".join(f"{b.name}({b.bank_code})" for b in (found or banks)) or "없음"
    if not found:
        raise NotFoundException(code="BANK_NOT_FOUND", message=f"'{ref}' 은행을 찾을 수 없습니다. 보낼 수 있는 은행: {candidates}. 사용자에게 어느 은행인지 물어보세요.")
    raise BadRequestException(code="BANK_AMBIGUOUS", message=f"'{ref}'에 해당하는 은행이 여러 개입니다: {candidates}. 사용자에게 어느 은행인지 물어보세요.")


async def _prepare_interbank(db: AsyncSession, user: UserResponse, args: PrepareTransferArgs, from_id: int, bank: BankInfo) -> TransferAction:
    """타행 이체 초안. 받는 분 이름은 허브 수취 조회(돈이 움직이지 않음)로 받는다.
    실제 송금은 사용자가 확인 카드를 눌렀을 때 기존 타행 이체 서비스가 한다 (SPEC 6절: 돈이 움직이는 허브 호출을 LLM 도구로 주지 않는다)."""
    to_account = args.to_account_num.strip()
    holder = (await interbank_service.inquiry(InquiryRequest(to_bank=bank.bank_code, to_account=to_account))).holder_name
    async with db.begin():
        sender = await account_service.get_owned(db, KINDS["checking"], from_id, user)
        require_open(sender)
        await check_transfer_limits(db, sender, args.amount)  # 잔액·1회·1일 한도 (확인할 때 다시 검사한다)
        draft = TransferDraft(
            draft_id=secrets.token_urlsafe(32), user_id=user.user_id, from_checking_account_id=from_id,
            to_account_num=to_account, to_bank=bank.bank_code, recipient_name=holder[:50], amount=args.amount,
            expires_at=datetime.now(timezone.utc) + DRAFT_TTL,
        )
        db.add(draft)
        from_name = await account_name(db, sender)
    return TransferAction(
        draft_id=draft.draft_id, from_account_id=from_id, from_account_name=from_name,
        from_account_num_masked=mask_num(sender.account_num), recipient_name=holder,
        to_account_num_masked=mask_num(to_account), amount=args.amount,
        expected_balance_after=sender.balance - args.amount, expires_at=draft.expires_at, to_bank_name=bank.name,
    )


async def _maybe_other_bank(account_num: str) -> NotFoundException:
    """은행을 말하지 않은 계좌번호가 우리 은행에 없을 때: 다른 은행 계좌일 수 있으니 어느 은행인지 되묻게 한다 (C-128)."""
    try:
        banks = ", ".join(f"{b.name}({b.bank_code})" for b in await interbank_service.banks())
    except ApiException:  # 타행 이체가 꺼져 있거나 허브에 닿지 않으면 예전처럼 '계좌 없음'
        return NotFoundException(code="ACCOUNT_NOT_FOUND", message="받는 계좌를 찾을 수 없습니다.")
    return NotFoundException(
        code="ACCOUNT_NOT_FOUND",
        message=f"{get_settings().bank_name}에 {account_num} 계좌가 없습니다. 다른 은행 계좌일 수 있으니 사용자에게 어느 은행인지 물어보세요. "
                f"보낼 수 있는 은행: {banks}. 은행을 알려 주면 to_bank에 넣어 다시 부르세요.",
    )


async def prepare_transfer(db: AsyncSession, user: UserResponse, args: PrepareTransferArgs) -> TransferAction:
    """이체 초안만 만든다. 돈은 움직이지 않는다 — 사용자가 화면에서 확인해야 /agent/transfers/{id}/confirm이 실행한다."""
    # 이름으로 계좌를 찾는 일은 서버가 한다 — 모델이 계좌 id를 짐작하거나 알고 있을 필요가 없다
    from_id, _, _ = await find_own_checking(db, user, args.from_account, "FROM")
    bank = await find_other_bank(args.to_bank) if args.to_bank else None
    if bank is not None:
        return await _prepare_interbank(db, user, args, from_id, bank)
    to_num = args.to_account_num.strip() if args.to_account_num is not None else (
        await find_own_checking(db, user, args.to_account, "TO")
    )[1]
    data = TransferTarget(  # 초안에는 계좌 비밀번호가 필요 없다. 확인(confirm) 때만 받는다
        from_checking_account_id=from_id, to_account_num=to_num, amount=args.amount
    )
    # 소유권·받는 계좌·같은 계좌·잔액·1회/1일 한도를 기존 이체와 같은 코드로 검사한다
    try:
        sender, receiver, recipient_name = await transfer_service.preview(db, data, user)
    except NotFoundException as e:
        if e.code != "ACCOUNT_NOT_FOUND" or args.to_account_num is None:
            raise
        raise await _maybe_other_bank(args.to_account_num) from e
    async with db.begin():
        draft = TransferDraft(
            draft_id=secrets.token_urlsafe(32), user_id=user.user_id,
            from_checking_account_id=sender.checking_account_id, to_account_num=receiver.account_num,
            recipient_name=recipient_name, amount=data.amount,
            expires_at=datetime.now(timezone.utc) + DRAFT_TTL,
        )
        db.add(draft)
        from_name = await account_name(db, sender)
    return TransferAction(
        draft_id=draft.draft_id, from_account_id=sender.checking_account_id, from_account_name=from_name,
        from_account_num_masked=mask_num(sender.account_num), recipient_name=recipient_name,
        to_account_num_masked=mask_num(receiver.account_num), amount=data.amount,
        expected_balance_after=sender.balance - data.amount, expires_at=draft.expires_at,
    )
