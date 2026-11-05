from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.exceptions import BadRequestException, NotFoundException
from avengers_bank.domains.products.models import AccountProduct, CardProduct
from avengers_bank.domains.products.repository import product_repository


class ProductService:
    async def get_account_products(
        self, db: AsyncSession, type: str | None = None
    ) -> list[AccountProduct]:
        return await product_repository.find_account_products(db, type)

    async def get_account_product(self, db: AsyncSession, product_id: int) -> AccountProduct:
        product = await product_repository.find_account_product_by_id(db, product_id)
        if product is None:
            raise NotFoundException(
                code="ACCOUNT_PRODUCT_NOT_FOUND", message="계좌 상품을 찾을 수 없습니다."
            )
        return product

    async def get_card_products(
        self, db: AsyncSession, type: str | None = None
    ) -> list[CardProduct]:
        return await product_repository.find_card_products(db, type)

    async def get_card_product(self, db: AsyncSession, product_id: int) -> CardProduct:
        product = await product_repository.find_card_product_by_id(db, product_id)
        if product is None:
            raise NotFoundException(
                code="CARD_PRODUCT_NOT_FOUND", message="카드 상품을 찾을 수 없습니다."
            )
        return product

    # accounts / cards 도메인이 계좌 개설·카드 발급 때 부르는 "상품 종류 검증"
    async def require_account_product(
        self, db: AsyncSession, product_id: int, type: str
    ) -> AccountProduct:
        product = await self.get_account_product(db, product_id)
        if product.type != type:
            raise BadRequestException(
                code="PRODUCT_TYPE_MISMATCH", message="선택한 상품으로는 개설할 수 없는 계좌입니다."
            )
        return product

    async def require_card_product(
        self, db: AsyncSession, product_id: int, type: str
    ) -> CardProduct:
        product = await self.get_card_product(db, product_id)
        if product.type != type:
            raise BadRequestException(
                code="PRODUCT_TYPE_MISMATCH", message="선택한 상품으로는 발급할 수 없는 카드입니다."
            )
        return product


product_service = ProductService()
