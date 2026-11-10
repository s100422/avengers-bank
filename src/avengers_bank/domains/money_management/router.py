from fastapi import APIRouter

from avengers_bank.core.responses import error_responses

router = APIRouter(prefix="/money", tags=["money"], responses=error_responses(401, 422))
