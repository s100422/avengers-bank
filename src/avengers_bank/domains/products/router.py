from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.products.schemas import AccountProductResponse, CardProductResponse
from avengers_bank.domains.products.service import product_service

router = APIRouter(prefix="/products", tags=["products"], responses=error_responses(422))

DbSession = Annotated[AsyncSession, Depends(get_db)]


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
