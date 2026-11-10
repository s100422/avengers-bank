"""찜한 상품 (C-117): 상품 화면·홈의 하트와 AI 비서의 get_favorite_products가 같이 쓴다."""
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.exceptions import ConflictException
from avengers_bank.domains.products.models import AccountProduct, CardProduct, FavoriteProduct
from avengers_bank.domains.products.schemas import FavoriteProductResponse
from avengers_bank.domains.products.service import product_service

ProductType = Literal["CHECKING", "DEPOSIT", "SAVINGS", "CREDIT", "DEBIT"]
ACCOUNT_TYPES = {"CHECKING", "DEPOSIT", "SAVINGS"}


async def list_favorite_products(db: AsyncSession, user_id: int) -> list[FavoriteProductResponse]:
    """최근에 찜한 것이 위. 트랜잭션을 열지 않아 AI 도구(자기 세션)에서도 그대로 부른다."""
    favs = list(await db.scalars(
        select(FavoriteProduct).where(FavoriteProduct.user_id == user_id).order_by(FavoriteProduct.favorite_id.desc())
    ))
    account_ids = [f.product_id for f in favs if f.product_type in ACCOUNT_TYPES]
    card_ids = [f.product_id for f in favs if f.product_type not in ACCOUNT_TYPES]
    accounts = {p.product_id: p for p in await db.scalars(select(AccountProduct).where(AccountProduct.product_id.in_(account_ids)))}
    cards = {p.product_id: p for p in await db.scalars(select(CardProduct).where(CardProduct.product_id.in_(card_ids)))}
    out = []
    for f in favs:
        p = (accounts if f.product_type in ACCOUNT_TYPES else cards).get(f.product_id)
        if p is None or p.type != f.product_type:  # 상품이 없어졌거나 종류가 바뀐 행은 보이지 않는다
            continue
        out.append(FavoriteProductResponse(
            product_type=p.type, product_id=p.product_id, name=p.name, description=p.description,
            interest_rate=getattr(p, "interest_rate", None), min_amount=getattr(p, "min_amount", None),
            credit_limit=getattr(p, "credit_limit", None),
        ))
    return out


class FavoriteProductService:
    async def list(self, db: AsyncSession, user_id: int) -> list[FavoriteProductResponse]:
        async with db.begin():
            return await list_favorite_products(db, user_id)

    async def add(self, db: AsyncSession, user_id: int, product_type: ProductType, product_id: int) -> None:
        """이미 찜했으면 그대로 둔다 (두 번 눌러도, 동시에 눌러도 한 건)."""
        for _ in range(2):
            try:
                async with db.begin():
                    # 없는 상품(404)·종류가 다른 상품(400)은 기존 검증을 그대로 쓴다
                    if product_type in ACCOUNT_TYPES:
                        await product_service.require_account_product(db, product_id, product_type)
                    else:
                        await product_service.require_card_product(db, product_id, product_type)
                    if await self._find(db, user_id, product_type, product_id) is None:
                        db.add(FavoriteProduct(user_id=user_id, product_type=product_type, product_id=product_id))
                return
            except IntegrityError:  # 동시에 같은 상품을 찜함: 다시 확인한다
                continue
        raise ConflictException(code="FAVORITE_CONFLICT", message="찜을 저장하지 못했습니다. 다시 시도해 주세요.")

    async def remove(self, db: AsyncSession, user_id: int, product_type: ProductType, product_id: int) -> None:
        """찜하지 않은 상품을 지워도 성공 (하트를 빠르게 여러 번 눌러도 오류가 나지 않게)."""
        async with db.begin():
            await db.execute(delete(FavoriteProduct).where(
                FavoriteProduct.user_id == user_id, FavoriteProduct.product_type == product_type,
                FavoriteProduct.product_id == product_id,
            ))

    async def _find(self, db: AsyncSession, user_id: int, product_type: str, product_id: int) -> FavoriteProduct | None:
        return await db.scalar(select(FavoriteProduct).where(
            FavoriteProduct.user_id == user_id, FavoriteProduct.product_type == product_type,
            FavoriteProduct.product_id == product_id,
        ))


favorite_product_service = FavoriteProductService()
