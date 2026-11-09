"""로그인한 사용자가 쓰는 타행 이체 API. (허브가 부르는 API는 receiver.py)"""
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.database import get_db
from avengers_bank.core.dependencies import get_current_user
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.interbank.schemas import (
    BankInfo,
    InquiryRequest,
    InquiryResponse,
    InterbankResponse,
    InterbankSend,
)
from avengers_bank.domains.interbank.service import interbank_service
from avengers_bank.domains.users.schemas import UserResponse

router = APIRouter(
    prefix="/interbank-transfers", tags=["interbank"], responses=error_responses(401, 422)
)

DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]
FAILURES = error_responses(400, 404, 503)


@router.get("/banks", response_model=SuccessResponse[list[BankInfo]], responses=FAILURES)
async def banks(_: CurrentUser):
    return SuccessResponse[list[BankInfo]](data=await interbank_service.banks())


@router.post("/inquiry", response_model=SuccessResponse[InquiryResponse], responses=FAILURES)
async def inquiry(data: InquiryRequest, _: CurrentUser):
    return SuccessResponse[InquiryResponse](data=await interbank_service.inquiry(data))


@router.post(
    "", response_model=SuccessResponse[InterbankResponse], status_code=status.HTTP_201_CREATED, responses=FAILURES
)
async def send(data: InterbankSend, db: DbSession, user: CurrentUser):
    result = await interbank_service.send(db, data, user)
    message = "이체가 완료되었습니다." if result.status == "COMPLETED" else "이체 결과를 확인하고 있습니다."
    return SuccessResponse[InterbankResponse](data=result, message=message)


@router.get("/{transfer_id}", response_model=SuccessResponse[InterbankResponse], responses=FAILURES)
async def get_status(transfer_id: str, db: DbSession, user: CurrentUser):
    return SuccessResponse[InterbankResponse](data=await interbank_service.status(db, transfer_id, user))
