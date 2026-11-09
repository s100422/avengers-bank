"""계좌 비밀번호 (숫자 4자리). 돈이 나가는 모든 요청에서 '돈이 빠져나가는 계좌'의 비밀번호를 확인한다.

보안 메모:
- 4자리는 경우의 수가 1만 개뿐이라 해시가 유출되면 argon2로도 오프라인 대입을 오래 막지 못한다.
  그래서 온라인 대입을 막는 **5회 잠금이 필수**다. 잠금 해제는 휴대폰 인증 후 재설정(2단계)으로만 한다.
- 같은 숫자 4개·연속 숫자는 거부한다 (전자금융감독규정 제33조 ②항 1호 취지: 추측하기 쉬운 비밀번호 금지).

트랜잭션 함정: 틀렸을 때 예외를 던지면 바깥 `async with db.begin()`이 롤백해서 실패 횟수 증가가 사라진다
(잠금이 영원히 안 걸린다). 그래서 서비스는 verify_account_password를 직접 부르지 말고 check_account_password로
'검증만 하는 짧은 트랜잭션'을 먼저 커밋한 뒤 본 작업 트랜잭션을 연다.
"""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from avengers_bank.core.exceptions import ApiException, BadRequestException, ForbiddenException
from avengers_bank.core.security import hash_password, verify_password
from avengers_bank.domains.accounts.kinds import AccountKind
from avengers_bank.domains.users.schemas import UserResponse

MAX_FAILURES = 5
FORMAT_MESSAGE = "계좌 비밀번호는 숫자 4자리이며, 같은 숫자나 연속된 숫자는 쓸 수 없습니다."
LOCKED_MESSAGE = "계좌 비밀번호를 5회 잘못 입력해 잠겼습니다. 계좌 상세에서 휴대폰 인증 후 재설정해 주세요."

ASCENDING = "0123456789"


def validate_account_password_format(raw: str) -> str:
    """규칙 위반이면 ValueError (스키마 검증기에서 쓰면 422). isdigit()은 '١'(아랍 숫자) 같은 것도 통과시켜 쓰지 않는다."""
    if (
        len(raw) != 4
        or any(c not in ASCENDING for c in raw)
        or len(set(raw)) == 1
        or raw in ASCENDING
        or raw in ASCENDING[::-1]
    ):
        raise ValueError(FORMAT_MESSAGE)
    return raw


async def set_account_password(db: AsyncSession, account, raw: str) -> None:
    """해시 저장 + 실패 횟수·잠금 초기화 (재설정이 잠금 해제를 겸한다). 호출한 쪽이 트랜잭션·형식 검사를 맡는다."""
    account.password_hash = await run_in_threadpool(hash_password, raw)
    account.password_failed_count = 0
    account.password_locked_at = None


async def verify_account_password(db: AsyncSession, account, raw: str) -> None:
    """account는 이미 FOR UPDATE로 잠근 행이어야 한다. 잠근 뒤 읽고·증가하므로 동시 요청이 직렬화돼
    5회 제한을 우회할 수 없다. 틀리면 실패 횟수를 올린 뒤 예외를 던진다 — 증가가 커밋되게 하는 건 호출한 쪽 책임
    (check_account_password 참고)."""
    if account.password_hash is None:
        raise BadRequestException(
            code="ACCOUNT_PASSWORD_NOT_SET", message="계좌 비밀번호가 설정되지 않았습니다. 계좌 상세에서 먼저 설정해 주세요."
        )
    if account.password_locked_at is not None:
        raise ForbiddenException(code="ACCOUNT_PASSWORD_LOCKED", message=LOCKED_MESSAGE)
    # argon2 검증(수십 ms)은 이벤트 루프를 막지 않게 스레드에서. 행 잠금은 쥔 채로 한다(그래야 직렬화된다)
    if await run_in_threadpool(verify_password, raw, account.password_hash):
        account.password_failed_count = 0
        return
    account.password_failed_count += 1
    if account.password_failed_count >= MAX_FAILURES:
        account.password_locked_at = datetime.now(timezone.utc)
        raise ForbiddenException(code="ACCOUNT_PASSWORD_LOCKED", message=LOCKED_MESSAGE)
    raise BadRequestException(
        code="ACCOUNT_PASSWORD_INCORRECT",
        message=f"계좌 비밀번호가 올바르지 않습니다. ({account.password_failed_count}/{MAX_FAILURES})",
    )


async def reset_account_password(
    db: AsyncSession, kind: AccountKind, account_id: int, raw: str, phone_verification_token: str, user: UserResponse
) -> None:
    """휴대폰 인증 증표로 계좌 비밀번호를 정한다(처음 설정·재설정 공통, 잠금 해제·실패 0 포함) + 알림 문자.

    본인 계좌만(남의 계좌 404). 증표는 이 사용자가 등록 번호로 받은 ACCOUNT_PASSWORD_RESET용만 받고, 같은 트랜잭션에서
    1회 사용한다(실패해 롤백되면 사용도 되돌려진다). 계좌 행을 잠근 뒤 바꾼다(규칙 9: 동시에 오는 이체의 검증과 줄을 선다).
    """
    from avengers_bank.domains.accounts.repository import account_repository
    from avengers_bank.domains.accounts.service import account_service
    from avengers_bank.domains.verification.service import consume_verification, send_notice

    async with db.begin():
        account = await account_service.get_owned(db, kind, account_id, user)  # 404를 증표 사용보다 먼저
        await consume_verification(
            db, phone_verification_token, "ACCOUNT_PASSWORD_RESET", phone=user.phone, user_id=user.user_id
        )
        account = await account_repository.lock_account(db, kind, account_id)
        await set_account_password(db, account, raw)
        account_num = account.account_num
    await send_notice(
        user.phone, f"계좌({account_num}) 비밀번호가 설정되었습니다. 본인이 아니라면 바로 고객센터로 연락해 주세요."
    )


async def check_account_password(
    db: AsyncSession, kind: AccountKind, account_id: int, raw: str, user: UserResponse
) -> None:
    """돈이 나가기 전에 부른다. 본인 계좌인지 보고(남의 계좌는 404), 그 계좌만 잠근 짧은 트랜잭션에서 검증해 커밋한다.

    - 실패 횟수 증가는 예외를 블록 안에서 잡아 두고 커밋한 뒤 블록 밖에서 던진다 (users/service.py refresh()와 같은 방식).
    - 본 작업 트랜잭션보다 먼저 따로 커밋하는 이유: 본 작업 중(예금 개설의 계좌 INSERT 등)에 예외로 실패 횟수만
      커밋하려면 그 앞의 작업까지 커밋돼 버린다. 검증을 앞으로 빼면 '실패면 여기서 끝, 성공이면 본 작업'으로 단순하다.
    - 이 트랜잭션은 계좌 행 하나만 잠그고 끝나므로 규칙 9의 잠금 순서와 엮여 데드락이 생기지 않는다.
    - 검증 성공과 본 작업 사이의 틈: 그사이 누가 5회 틀려 잠가도 이미 맞는 비밀번호를 낸 이 요청은 진행된다.
      맞는 비밀번호를 알아야 통과하므로 무차별 대입에는 쓸 수 없다. 잔액·한도·상태는 본 작업이 다시 잠그고 검사한다.
    """
    # 순환 import 방지: schemas(→ 이 모듈) ← repository·service가 schemas를 import한다
    from avengers_bank.domains.accounts.repository import account_repository
    from avengers_bank.domains.accounts.service import account_service

    error: ApiException | None = None
    async with db.begin():
        await account_service.get_owned(db, kind, account_id, user)
        account = await account_repository.lock_account(db, kind, account_id)
        try:
            await verify_account_password(db, account, raw)
        except ApiException as e:
            error = e  # 여기서 던지면 롤백돼 실패 횟수가 사라진다. 커밋 뒤에 던진다
    if error:
        raise error
