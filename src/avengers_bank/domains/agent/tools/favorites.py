from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.domains.agent.tools.accounts import NoArgs
from avengers_bank.domains.products.favorites import list_favorite_products
from avengers_bank.domains.products.schemas import FavoriteProductResponse
from avengers_bank.domains.users.schemas import UserResponse


class FavoriteProductsResult(BaseModel):
    favorites: list[FavoriteProductResponse]  # 최근에 찜한 것이 위


async def get_favorite_products(db: AsyncSession, user: UserResponse, args: NoArgs) -> FavoriteProductsResult:
    """조회만 한다. 찜 추가·해제는 화면에서만 (C-117)."""
    return FavoriteProductsResult(favorites=await list_favorite_products(db, user.user_id))
