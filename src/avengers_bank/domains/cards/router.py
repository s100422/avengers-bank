from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.cards.kinds import CardType
from avengers_bank.domains.cards.schemas import (
    BillCreate,
    BillDetailResponse,
    BillResponse,
    CardHistoryResponse,
    CardPaymentCreate,
    CardPaymentResponse,
    CardResponse,
    CardSummaryResponse,
    CreditCardCreate,
    CreditCardResponse,
    DebitCardCreate,
    DebitCardResponse,
)
from avengers_bank.domains.cards.service import card_service
from avengers_bank.domains.users.schemas import UserResponse

router = APIRouter(prefix="/cards", tags=["cards"], responses=error_responses(401, 422))

DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]
ISSUED = "카드가 발급되었습니다."


@router.get("", response_model=SuccessResponse[list[CardSummaryResponse]])
async def list_my_cards(db: DbSession, user: CurrentUser):
    return SuccessResponse[list[CardSummaryResponse]](data=await card_service.get_my_cards(db, user))


@router.post(
    "/credit",
    response_model=SuccessResponse[CreditCardResponse],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 404),
)
async def issue_credit(data: CreditCardCreate, db: DbSession, user: CurrentUser):
    card = await card_service.issue_credit(db, data, user)
    return SuccessResponse[CreditCardResponse](data=card, message=ISSUED)


@router.post(
    "/debit",
    response_model=SuccessResponse[DebitCardResponse],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 404),
)
async def issue_debit(data: DebitCardCreate, db: DbSession, user: CurrentUser):
    card = await card_service.issue_debit(db, data, user)
    return SuccessResponse[DebitCardResponse](data=card, message=ISSUED)


@router.get(
    "/{type}/{card_id}",
    response_model=SuccessResponse[CardResponse],
    responses=error_responses(404),
)
async def get_card(type: CardType, card_id: int, db: DbSession, user: CurrentUser):
    return SuccessResponse[CardResponse](data=await card_service.get_card(db, type, card_id, user))


@router.get(
    "/{type}/{card_id}/histories",
    response_model=SuccessResponse[list[CardHistoryResponse]],
    responses=error_responses(404),
)
async def get_histories(
    type: CardType,
    card_id: int,
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    histories = await card_service.get_histories(db, type, card_id, user, limit, offset)
    return SuccessResponse[list[CardHistoryResponse]](data=histories)


@router.post(
    "/{type}/{card_id}/payments",
    response_model=SuccessResponse[CardPaymentResponse],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 404),
)
async def pay(type: CardType, card_id: int, data: CardPaymentCreate, db: DbSession, user: CurrentUser):
    result = await card_service.pay(db, type, card_id, data, user)
    return SuccessResponse[CardPaymentResponse](data=result, message="결제가 등록되었습니다.")


# ── 신용카드 청구서 ──────────────────────────────────────────────────


@router.post(
    "/credit/{card_id}/bills",
    response_model=SuccessResponse[BillResponse],
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 404, 409),
)
async def create_bill(card_id: int, data: BillCreate, db: DbSession, user: CurrentUser):
    bill = await card_service.create_bill(db, card_id, data, user)
    return SuccessResponse[BillResponse](data=bill, message="청구서가 생성되었습니다.")


@router.get(
    "/credit/{card_id}/bills",
    response_model=SuccessResponse[list[BillResponse]],
    responses=error_responses(404),
)
async def list_bills(card_id: int, db: DbSession, user: CurrentUser):
    return SuccessResponse[list[BillResponse]](data=await card_service.get_bills(db, card_id, user))


@router.get(
    "/credit/{card_id}/bills/{bill_id}",
    response_model=SuccessResponse[BillDetailResponse],
    responses=error_responses(404),
)
async def get_bill(card_id: int, bill_id: int, db: DbSession, user: CurrentUser):
    return SuccessResponse[BillDetailResponse](data=await card_service.get_bill(db, card_id, bill_id, user))


@router.post(
    "/credit/{card_id}/bills/{bill_id}/payments",
    response_model=SuccessResponse[BillResponse],
    responses=error_responses(400, 404, 409),
)
async def pay_bill(card_id: int, bill_id: int, db: DbSession, user: CurrentUser):
    bill = await card_service.pay_bill(db, card_id, bill_id, user)
    return SuccessResponse[BillResponse](data=bill, message="청구서 납부가 완료되었습니다.")
