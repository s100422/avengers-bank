import re
import secrets
from datetime import datetime, timedelta, timezone

from pydantic import Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.exceptions import BadRequestException, NotFoundException
from avengers_bank.domains.accounts.kinds import KINDS
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.accounts.schemas import Amount
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
        default=None, min_length=1, max_length=20,
        description="받는 계좌가 다른 사람 계좌일 때 사용자가 알려 준 계좌번호 전체. to_account와 둘 중 하나만 쓴다")
    amount: Amount = Field(description="이체 금액(원, 양의 정수)")

    @model_validator(mode="after")
    def _exactly_one_target(self):
        if (self.to_account is None) == (self.to_account_num is None):
            raise ValueError("to_account(내 계좌)와 to_account_num(다른 사람 계좌) 중 하나만 넣어야 합니다.")
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


async def prepare_transfer(db: AsyncSession, user: UserResponse, args: PrepareTransferArgs) -> TransferAction:
    """이체 초안만 만든다. 돈은 움직이지 않는다 — 사용자가 화면에서 확인해야 /agent/transfers/{id}/confirm이 실행한다."""
    # 이름으로 계좌를 찾는 일은 서버가 한다 — 모델이 계좌 id를 짐작하거나 알고 있을 필요가 없다
    from_id, _, _ = await find_own_checking(db, user, args.from_account, "FROM")
    to_num = args.to_account_num.strip() if args.to_account_num is not None else (
        await find_own_checking(db, user, args.to_account, "TO")
    )[1]
    data = TransferTarget(  # 초안에는 계좌 비밀번호가 필요 없다. 확인(confirm) 때만 받는다
        from_checking_account_id=from_id, to_account_num=to_num, amount=args.amount
    )
    # 소유권·받는 계좌·같은 계좌·잔액·1회/1일 한도를 기존 이체와 같은 코드로 검사한다
    sender, receiver, recipient_name = await transfer_service.preview(db, data, user)
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
