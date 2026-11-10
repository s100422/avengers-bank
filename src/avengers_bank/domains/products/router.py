from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.products.favorites import ProductType, favorite_product_service
from avengers_bank.domains.products.schemas import AccountProductResponse, CardProductResponse, FavoriteProductResponse
from avengers_bank.domains.products.service import product_service
from avengers_bank.domains.users.schemas import UserResponse

router = APIRouter(prefix="/products", tags=["products"], responses=error_responses(422))

DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]


@router.get("/accounts", response_model=SuccessResponse[list[AccountProductResponse]])
async def list_account_products(
    db: DbSession, type: Literal["CHECKING", "DEPOSIT", "SAVINGS"] | None = None
):
    products = await product_service.get_account_products(db, type)
    return SuccessResponse[list[AccountProductResponse]](data=products)


@router.get(
    "/accounts/{product_id}",
    response_model=SuccessResponse[AccountProductResponse],
    responses=error_responses(404),
)
async def get_account_product(product_id: int, db: DbSession):
    product = await product_service.get_account_product(db, product_id)
    return SuccessResponse[AccountProductResponse](data=product)


@router.get("/cards", response_model=SuccessResponse[list[CardProductResponse]])
async def list_card_products(db: DbSession, type: Literal["CREDIT", "DEBIT"] | None = None):
    products = await product_service.get_card_products(db, type)
    return SuccessResponse[list[CardProductResponse]](data=products)


@router.get(
    "/cards/{product_id}",
    response_model=SuccessResponse[CardProductResponse],
    responses=error_responses(404),
)
async def get_card_product(product_id: int, db: DbSession):
    product = await product_service.get_card_product(db, product_id)
    return SuccessResponse[CardProductResponse](data=product)


# 찜한 상품 (C-117). 상품 목록과 달리 로그인이 필요하다
@router.get(
    "/favorites",
    response_model=SuccessResponse[list[FavoriteProductResponse]],
    responses=error_responses(401),
)
async def list_favorite_products(db: DbSession, user: CurrentUser):
    data = await favorite_product_service.list(db, user.user_id)
    return SuccessResponse[list[FavoriteProductResponse]](data=data)


@router.put(
    "/favorites/{product_type}/{product_id}",
    response_model=SuccessResponse[None],
    responses=error_responses(400, 401, 404, 409),
)
async def add_favorite_product(product_type: ProductType, product_id: int, db: DbSession, user: CurrentUser):
    await favorite_product_service.add(db, user.user_id, product_type, product_id)
    return SuccessResponse[None](data=None, message="찜했습니다.")


@router.delete(
    "/favorites/{product_type}/{product_id}",
    response_model=SuccessResponse[None],
    responses=error_responses(401),
)
async def remove_favorite_product(product_type: ProductType, product_id: int, db: DbSession, user: CurrentUser):
    await favorite_product_service.remove(db, user.user_id, product_type, product_id)
    return SuccessResponse[None](data=None, message="찜을 해제했습니다.")
