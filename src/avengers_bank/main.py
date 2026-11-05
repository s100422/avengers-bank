import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from avengers_bank.core.config import get_settings
from avengers_bank.core.database import engine
from avengers_bank.core.exception_handlers import register_exception_handlers
from avengers_bank.core.exceptions import ApiException
from avengers_bank.core.responses import SuccessResponse, error_responses
from avengers_bank.domains.accounts.dev import router as dev_router
from avengers_bank.domains.accounts.router import router as account_router
from avengers_bank.domains.cards.router import router as card_router
from avengers_bank.domains.products.router import router as product_router
from avengers_bank.domains.transfers.router import router as transfer_router
from avengers_bank.domains.users.router import router as user_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().enable_dev_endpoints:
        # 운영에서 켜져 있으면 누구나 잔액을 채울 수 있다. 시작 로그로 알아볼 수 있게 한다 (C-050)
        logger.warning("ENABLE_DEV_ENDPOINTS가 켜져 있습니다: /dev/... 개발용 충전 API가 열려 있습니다. 운영 환경에서는 꺼야 합니다.")
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="AvengersBank", lifespan=lifespan, responses=error_responses(500))
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
register_exception_handlers(app)
app.include_router(user_router)
app.include_router(product_router)
app.include_router(account_router)
app.include_router(transfer_router)
app.include_router(card_router)
if get_settings().enable_dev_endpoints:
    app.include_router(dev_router)


@app.get("/", response_model=SuccessResponse[dict[str, str]])
async def get_root():
    return SuccessResponse[dict[str, str]](data={"Hello": "AvengersBank"})


@app.get("/health", response_model=SuccessResponse[dict[str, str]], responses=error_responses(503))
async def get_health():
    """DB까지 연결되는지 확인한다 (C-046). 실패 원인은 응답에 싣지 않고 로그에만 남긴다."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("health check: DB 연결 실패")
        raise ApiException(503, "DB_UNAVAILABLE", "데이터베이스에 연결할 수 없습니다.") from None
    return SuccessResponse[dict[str, str]](data={"status": "ok"})
