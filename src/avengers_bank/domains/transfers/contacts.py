"""이체 화면의 '최근 / 자주 쓰는' 목록과 우리 은행 수취 조회."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import NotFoundException
from avengers_bank.domains.accounts.kinds import TRANSFER_OUT
from avengers_bank.domains.accounts.models import CheckingAccount, CheckingAccountHistory
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.interbank.models import InterbankTransfer
from avengers_bank.domains.transfers.models import FavoriteAccount
from avengers_bank.domains.transfers.schemas import FavoriteCreate, FavoriteResponse, RecentContact
from avengers_bank.domains.users.models import User
from avengers_bank.domains.users.schemas import UserResponse

RECENT_LIMIT = 20


def mask_name(name: str) -> str:
    """홍길동 → 홍*동, 홍길 → 홍*. 우리 은행 수취 조회는 이름을 가려서 돌려준다."""
    if len(name) <= 1:
        return name
    return name[0] + "*" * max(len(name) - 2, 1) + (name[-1] if len(name) > 2 else "")


class ContactService:
    async def inquiry(self, db: AsyncSession, to_account_num: str) -> tuple[str, str]:
        """우리 은행 계좌의 (계좌번호, 가린 예금주 이름). 닫힌 계좌는 없는 계좌와 같다."""
        async with db.begin():
            account = await account_repository.find_checking_by_account_num(db, to_account_num)
            if account is None:
                raise NotFoundException(code="ACCOUNT_NOT_FOUND", message="받는 계좌를 찾을 수 없습니다.")
            return account.account_num, mask_name((await db.get(User, account.user_id)).name)

    async def recent(self, db: AsyncSession, user: UserResponse) -> list[RecentContact]:
        """내가 이체한 상대(우리 은행 + 타행), 최근 순. 내 계좌끼리 보낸 것과 실패한 타행 이체는 뺀다."""
        own_bank = get_settings().bank_name
        async with db.begin():
            mine = set(await db.scalars(select(CheckingAccount.account_num).where(CheckingAccount.user_id == user.user_id)))
            own = await db.execute(
                select(CheckingAccountHistory.counterpart_account, CheckingAccountHistory.counterpart_name, CheckingAccountHistory.date)
                .join(CheckingAccount, CheckingAccount.checking_account_id == CheckingAccountHistory.checking_account_id)
                .where(CheckingAccount.user_id == user.user_id, CheckingAccountHistory.type == TRANSFER_OUT)
                .order_by(CheckingAccountHistory.date.desc()).limit(100)
            )
            other = await db.execute(
                select(InterbankTransfer.peer_bank, InterbankTransfer.peer_bank_name, InterbankTransfer.peer_account,
                       InterbankTransfer.peer_name, InterbankTransfer.created_at)
                .join(CheckingAccount, CheckingAccount.checking_account_id == InterbankTransfer.checking_account_id)
                .where(CheckingAccount.user_id == user.user_id, InterbankTransfer.direction == "OUT",
                       InterbankTransfer.status != "FAILED")
                .order_by(InterbankTransfer.created_at.desc()).limit(100)
            )
            rows = [("", own_bank, a, n, d) for a, n, d in own if a and a not in mine]
            rows += [(b, bn or f"은행 {b}", a, n, d) for b, bn, a, n, d in other]
            favorites = {(f.bank_code, f.account): f.favorite_id for f in await self._favorites(db, user)}
        latest: dict[tuple[str, str], RecentContact] = {}
        stamp: dict[tuple[str, str], object] = {}
        for bank, bank_name, account, name, when in rows:
            key = (bank, account)
            # SQLite는 시간대 없이 돌려줘 비교가 어긋날 수 있어 날짜 비교는 문자열로 한다 (같은 형식이면 순서가 같다)
            if key not in latest or str(when) > str(stamp[key]):
                latest[key] = RecentContact(bank_code=bank, bank_name=bank_name, account=account, name=name,
                                            favorite_id=favorites.get(key))
                stamp[key] = when
            elif latest[key].name is None and name:
                latest[key].name = name
        ordered = sorted(latest, key=lambda k: str(stamp[k]), reverse=True)
        return [latest[k] for k in ordered[:RECENT_LIMIT]]

    async def favorites(self, db: AsyncSession, user: UserResponse) -> list[FavoriteResponse]:
        async with db.begin():
            return [FavoriteResponse.model_validate(f) for f in await self._favorites(db, user)]

    async def add_favorite(self, db: AsyncSession, data: FavoriteCreate, user: UserResponse) -> FavoriteResponse:
        """이미 있으면 그대로 돌려준다 (별을 두 번 눌러도, 동시에 눌러도 한 건)."""
        for _ in range(2):
            try:
                async with db.begin():
                    found = await self._find(db, user, data.bank_code, data.account)
                    if found is None:
                        found = FavoriteAccount(user_id=user.user_id, **data.model_dump())
                        db.add(found)
                        await db.flush()
                    return FavoriteResponse.model_validate(found)
            except IntegrityError:  # 동시에 같은 계좌를 추가함: 다시 읽는다
                continue
        raise NotFoundException(code="FAVORITE_NOT_FOUND", message="자주 쓰는 계좌를 저장하지 못했습니다.")

    async def remove_favorite(self, db: AsyncSession, favorite_id: int, user: UserResponse) -> None:
        async with db.begin():
            found = await db.get(FavoriteAccount, favorite_id)
            if found is None or found.user_id != user.user_id:  # 남의 것도 없는 것과 같다
                raise NotFoundException(code="FAVORITE_NOT_FOUND", message="자주 쓰는 계좌를 찾을 수 없습니다.")
            await db.delete(found)

    async def _favorites(self, db: AsyncSession, user: UserResponse) -> list[FavoriteAccount]:
        rows = await db.scalars(
            select(FavoriteAccount).where(FavoriteAccount.user_id == user.user_id).order_by(FavoriteAccount.favorite_id.desc())
        )
        return list(rows)

    async def _find(self, db: AsyncSession, user: UserResponse, bank_code: str, account: str) -> FavoriteAccount | None:
        return await db.scalar(select(FavoriteAccount).where(
            FavoriteAccount.user_id == user.user_id, FavoriteAccount.bank_code == bank_code,
            FavoriteAccount.account == account,
        ))


contact_service = ContactService()
