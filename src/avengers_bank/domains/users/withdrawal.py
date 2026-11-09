"""회원 탈퇴 (소프트 삭제).

조건: 예금·적금 모두 해지(CLOSED), 입출금 계좌 잔액 모두 0원, 신용카드 미결제액(outstanding_amount: 청구 전 사용액 +
미납 청구서) 0원. 본인 확인: 로그인 비밀번호(로그인 실패 카운터와 같은 규칙) + 등록 휴대폰 인증번호(purpose WITHDRAWAL).

무엇을 하나 (한 트랜잭션):
- 가린다: users 행은 남기고(deleted_at) 이름·닉네임·전화번호·비밀번호를 지운다. login_id는 남겨 같은 아이디 재가입을 막는다
  (가입은 기존 409 "이미 사용 중인 아이디입니다." 그대로 — 탈퇴한 아이디라는 사실을 드러내지 않는다).
- 보존한다: 계좌·거래내역·카드·카드 사용내역·청구서·약관 동의 기록. 전자금융거래법상 거래 기록 보존 의무가 있어서다.
  보존 기간(예: 5년)과 기간이 지난 뒤 파기 절차는 법 확인 필요 — 지금은 지우는 작업이 없다.
- 닫는다: 입출금 계좌(closed_at) — 남이 이 계좌로 이체하면 돈이 묶이므로 없는 계좌처럼 거절한다(accounts/service.py
  require_open). 카드는 신용·체크 모두 CLOSED — 탈퇴 회원의 카드로 결제가 일어나지 않게.
- 끊는다: 모든 갱신 토큰 폐기(WITHDRAWN)와 등록 기기 해제. 액세스 토큰도 다음 요청부터 401(세션 확인 C-087 + deleted_at 확인).
- 지운다: AI 대화·메시지·이체 초안(개인 대화이고 거래 기록이 아니다), 인증번호 행(이번 탈퇴 인증 포함 — 소비한 뒤).

잠금 순서 (docs/ERD.md 규칙 9): users → 입출금 계좌(ID 오름차순) → 예금·적금 → 카드 → (갱신 토큰 폐기).
- 탈퇴와 '남이 내 계좌로 입금'이 겹치는 경우: 둘 다 그 입출금 계좌 행을 FOR UPDATE로 잠그므로 한 줄로 선다.
  입금이 먼저면 탈퇴는 잠근 뒤 잔액 > 0을 보고 막힌다. 탈퇴가 먼저면 입금은 잠근 뒤 closed_at을 보고 404.
  잠그지 않고 읽으면 '잔액 0 확인' 직후 입금이 커밋돼 탈퇴한 회원의 계좌에 돈이 남는다(scripts/pg_withdrawal_concurrency.py 대조군).
"""

from datetime import datetime, timezone

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from avengers_bank.core.exceptions import ApiException, BadRequestException, UnauthorizedException
from avengers_bank.core.security import verify_password
from avengers_bank.domains.accounts.kinds import KINDS as ACCOUNT_KINDS
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.agent.models import AgentConversation, AgentMessage, TransferDraft
from avengers_bank.domains.cards.kinds import KINDS as CARD_KINDS
from avengers_bank.domains.users.models import User
from avengers_bank.domains.users.repository import user_repository
from avengers_bank.domains.users.schemas import UserResponse, WithdrawalBlocker
from avengers_bank.domains.users.service import MAX_LOGIN_FAILURES, _busy, _locked, user_service
from avengers_bank.domains.verification.models import VerificationCode
from avengers_bank.domains.verification.service import consume_verification

WITHDRAWN_NAME = "탈퇴회원"
# argon2 해시 모양이 아니라 verify_password가 어떤 비밀번호에도 False (UnknownHashError). 로그인은 그 전에 탈퇴 회원을 걸러 낸다
WITHDRAWN_PASSWORD_HASH = "!withdrawn"
# phone은 NOT NULL 그대로 두고 빈 문자열로 가린다: nullable로 바꾸면 UserResponse.phone 등 '언제나 있는 값'으로 쓰는
# 코드를 모두 고쳐야 하는데, 탈퇴 회원은 로그인할 수 없어 그 값을 읽을 일이 없다. 탈퇴 여부는 deleted_at이 말한다
WITHDRAWN_PHONE = ""


def _invalid_token() -> UnauthorizedException:
    return UnauthorizedException(message="유효하지 않거나 만료된 토큰입니다.", code="INVALID_TOKEN")


async def _rows(db: AsyncSession, model, id_column: str, user_id: int, lock: bool) -> list:
    stmt = select(model).where(model.user_id == user_id).order_by(getattr(model, id_column))
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return list(await db.scalars(stmt))


async def _load(db: AsyncSession, user_id: int, lock: bool) -> dict[str, list]:
    """그 사용자의 계좌·카드. lock=True면 규칙 9 순서(입출금 ID 오름차순 → 예금·적금 → 카드)로 잠그며 읽는다."""
    checking = await account_repository.find_by_user_id(db, ACCOUNT_KINDS["checking"], user_id)
    if lock:
        # 이체·결제와 같은 함수로 잠근다(같은 순서, PostgreSQL 대조군 스크립트가 이 함수를 바꿔 끼운다)
        checking = await account_repository.lock_checking_accounts(db, [a.checking_account_id for a in checking])
    rows = {"checking": checking}
    for name in ("deposit", "savings"):
        kind = ACCOUNT_KINDS[name]
        rows[name] = await _rows(db, kind.model, kind.id_column, user_id, lock)
    for name in ("credit", "debit"):
        kind = CARD_KINDS[name]
        rows[name] = await _rows(db, kind.model, kind.id_column, user_id, lock)
    return rows


def _blockers(rows: dict[str, list]) -> list[WithdrawalBlocker]:
    """화면이 '무엇을 먼저 해야 하는지' 보여 줄 순서: 예금·적금 해지(돈이 입출금으로 온다) → 입출금 잔액 → 카드."""
    out = []
    for name, code, label in (("deposit", "ACTIVE_DEPOSIT", "예금"), ("savings", "ACTIVE_SAVINGS", "적금")):
        id_column = ACCOUNT_KINDS[name].id_column
        out += [
            WithdrawalBlocker(
                code=code, message=f"해지하지 않은 {label}이 있습니다: {a.account_num}",
                account_type=name, account_id=getattr(a, id_column),
            )
            for a in rows[name] if a.status != "CLOSED"
        ]
    out += [
        WithdrawalBlocker(
            code="CHECKING_BALANCE", message=f"잔액이 남은 입출금 계좌가 있습니다: {a.account_num}({a.balance:,}원)",
            account_type="checking", account_id=a.checking_account_id,
        )
        for a in rows["checking"] if a.closed_at is None and a.balance > 0
    ]
    out += [
        WithdrawalBlocker(
            code="CARD_UNPAID", message=f"결제하지 않은 신용카드 금액이 있습니다: {c.card_num}({c.outstanding_amount:,}원)",
            card_id=c.credit_card_id,
        )
        for c in rows["credit"] if c.outstanding_amount > 0  # 청구 전 사용액 + 미납 청구서 (ERD 규칙 4)
    ]
    return out


def _blocked(blockers: list[WithdrawalBlocker]) -> BadRequestException:
    # 오류 응답의 details는 입력 검증 형식이라 사유 목록을 담지 않는다. 첫 사유만 알리고, 목록은 GET이 준다
    extra = f" 외 {len(blockers) - 1}건" if len(blockers) > 1 else ""
    return BadRequestException(code="WITHDRAWAL_BLOCKED", message=f"탈퇴할 수 없습니다. {blockers[0].message}{extra}")


async def get_blockers(db: AsyncSession, user: UserResponse) -> list[WithdrawalBlocker]:
    """탈퇴 가능 여부 미리 보기 (잠그지 않는다 — 실제 탈퇴는 잠근 뒤 다시 검사한다)."""
    async with db.begin():
        return _blockers(await _load(db, user.user_id, lock=False))


async def _erase(db: AsyncSession, user: User, rows: dict[str, list]) -> None:
    now = datetime.now(timezone.utc)
    old_phone = user.phone
    for account in rows["checking"]:
        account.closed_at = now
    for card in rows["credit"] + rows["debit"]:
        card.status = "CLOSED"
    user.deleted_at = now
    user.name = WITHDRAWN_NAME
    user.nick_name = None
    user.phone = WITHDRAWN_PHONE
    user.phone_verified_at = None
    user.hashed_password = WITHDRAWN_PASSWORD_HASH
    user.failed_login_count = 0
    user.login_locked_at = None
    user.device_failed_login_count = 0
    user.device_login_locked_at = None
    await user_repository.revoke_user_refresh_tokens(db, user.user_id, now, "WITHDRAWN")
    await user_repository.revoke_user_devices(db, user.user_id, now)

    no_sync = {"synchronize_session": False}
    conversations = select(AgentConversation.conversation_id).where(AgentConversation.user_id == user.user_id)
    await db.execute(delete(AgentMessage).where(AgentMessage.conversation_id.in_(conversations)).execution_options(**no_sync))
    await db.execute(delete(AgentConversation).where(AgentConversation.user_id == user.user_id).execution_options(**no_sync))
    await db.execute(delete(TransferDraft).where(TransferDraft.user_id == user.user_id).execution_options(**no_sync))
    vc = VerificationCode
    await db.execute(
        delete(vc).where(or_(
            vc.user_id == user.user_id,
            # 가입 인증 행은 user_id가 없다(가입 전). 이미 쓴(consumed) 그 번호의 가입 인증만 지운다 —
            # 같은 번호로 지금 가입 중인 다른 사람의 인증까지 지우지 않게
            and_(vc.user_id.is_(None), vc.purpose == "SIGNUP_PHONE", vc.phone == old_phone, vc.consumed_at.is_not(None)),
        )).execution_options(**no_sync)
    )


async def withdraw(
    db: AsyncSession, current_user: UserResponse, current_password: str, phone_verification_token: str,
    raw_device_token: str | None = None,
) -> None:
    uid = current_user.user_id
    # 0) 막는 사유가 있으면 비밀번호를 세기 전에 알린다(잠그지 않은 미리 보기). 잠근 뒤 아래에서 다시 검사한다
    async with db.begin():
        blockers = _blockers(await _load(db, uid, lock=False))
    if blockers:
        raise _blocked(blockers)
    # 1) 비밀번호 틀림은 로그인과 같은 DB 카운터로 센다(users/service.py change_password와 같은 선증가, 먼저 커밋).
    #    채널도 같다: 요청의 기기 쿠키가 등록 기기면 등록 기기 카운터, 아니면 새 기기 카운터
    async with db.begin():
        device = await user_service._is_registered_device(db, uid, raw_device_token)
        count = await user_repository.count_login_attempt(db, uid, MAX_LOGIN_FAILURES, device)
        locked = count is None and (await user_repository.find_by_id(db, uid)).login_locked(device)
    if count is None:
        raise _locked() if locked else _busy()

    error: ApiException | None = None
    async with db.begin():
        user = await user_repository.lock_user(db, uid)  # users 먼저 (같은 사용자의 로그인·갱신과 한 줄로)
        if user is None or user.deleted_at is not None:
            raise _invalid_token()
        if user.login_locked(device):
            raise _locked()
        if not await run_in_threadpool(verify_password, current_password, user.hashed_password):
            # 잠금·카운트를 커밋해야 하므로 여기서 raise하지 않는다(raise하면 begin()이 롤백한다)
            if count >= MAX_LOGIN_FAILURES:
                await user_repository.lock_login(db, uid, datetime.now(timezone.utc), MAX_LOGIN_FAILURES, device)
                error = _locked()
            else:
                error = BadRequestException(code="INVALID_CURRENT_PASSWORD", message="현재 비밀번호가 올바르지 않습니다.")
        else:
            user.reset_login_failures(device)  # 비밀번호는 맞았다: 아래가 막혀도 이것은 커밋한다
            rows = await _load(db, uid, lock=True)  # 잠근 뒤 검사 (규칙 9)
            if blockers := _blockers(rows):
                error = _blocked(blockers)  # 미리 보기와 잠금 사이에 입금 등이 끼어들었다
            else:
                try:
                    # 이 사용자가 등록 번호로 받은 WITHDRAWAL 인증만. 실패하면 바뀐 것이 없다(조건 UPDATE 0행)
                    await consume_verification(db, phone_verification_token, "WITHDRAWAL", phone=user.phone, user_id=uid)
                except ApiException as e:
                    error = e
                else:
                    # 여기부터는 ApiException이 나지 않는다. DB 오류는 그대로 올라가 전체가 롤백된다
                    await _erase(db, user, rows)
    if error:
        raise error
