import secrets
from datetime import datetime, timedelta, timezone

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.exceptions import NotFoundException
from avengers_bank.domains.accounts.kinds import KINDS
from avengers_bank.domains.accounts.schemas import Amount
from avengers_bank.domains.accounts.service import account_service
from avengers_bank.domains.agent.models import TransferDraft
from avengers_bank.domains.agent.schemas import TransferAction
from avengers_bank.domains.agent.tools.common import ToolArgs, account_name, mask_num
from avengers_bank.domains.transfers.schemas import TransferTarget
from avengers_bank.domains.transfers.service import transfer_service
from avengers_bank.domains.users.schemas import UserResponse

DRAFT_TTL = timedelta(minutes=5)


class PrepareTransferArgs(ToolArgs):
    from_account_id: int = Field(description="출금할 입출금(checking) 계좌의 account_id (get_my_accounts 결과)")
    to_account_num: str = Field(min_length=1, max_length=20, description="받는 입출금 계좌번호 전체 (사용자가 알려 준 값)")
    amount: Amount = Field(description="이체 금액(원, 양의 정수)")


async def prepare_transfer(db: AsyncSession, user: UserResponse, args: PrepareTransferArgs) -> TransferAction:
    """이체 초안만 만든다. 돈은 움직이지 않는다 — 사용자가 화면에서 확인해야 /agent/transfers/{id}/confirm이 실행한다."""
    data = TransferTarget(  # 초안에는 계좌 비밀번호가 필요 없다. 확인(confirm) 때만 받는다
        from_checking_account_id=args.from_account_id, to_account_num=args.to_account_num.strip(), amount=args.amount
    )
    # 출금 계좌가 틀렸는지 받는 계좌가 틀렸는지 모델이 구분할 수 있게 출금 계좌부터 따로 확인한다
    try:
        await account_service.get_owned(db, KINDS["checking"], data.from_checking_account_id, user)
    except NotFoundException:
        raise NotFoundException(
            code="FROM_ACCOUNT_NOT_FOUND",
            message="출금 계좌를 찾을 수 없습니다. get_my_accounts 결과의 입출금 계좌 account_id를 써야 합니다.",
        ) from None
    finally:
        await db.rollback()  # 위 조회가 연 트랜잭션을 닫아야 preview의 db.begin()이 동작한다
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
