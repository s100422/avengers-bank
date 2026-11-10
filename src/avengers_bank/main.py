import asyncio
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
from avengers_bank.domains.agent.router import router as agent_router
from avengers_bank.domains.cards.router import router as card_router
from avengers_bank.domains.interbank.receiver import HubRequestError, SignResponses
from avengers_bank.domains.interbank.receiver import router as interbank_receiver_router
from avengers_bank.domains.interbank.router import router as interbank_router
from avengers_bank.domains.interbank.worker import run_forever as interbank_worker
from avengers_bank.domains.money_management.router import router as money_router
from avengers_bank.domains.notifications.router import router as notification_router
from avengers_bank.domains.products.router import router as product_router
from avengers_bank.domains.recovery.router import router as recovery_router
from avengers_bank.domains.terms.router import router as terms_router
from avengers_bank.domains.transfers.router import router as transfer_router
from avengers_bank.domains.users.router import router as user_router
from avengers_bank.domains.verification.dev import router as verification_dev_router
from avengers_bank.domains.verification.router import router as verification_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().enable_dev_endpoints:
        # 운영에서 켜져 있으면 누구나 잔액을 채울 수 있다. 시작 로그로 알아볼 수 있게 한다 (C-050)
        logger.warning("ENABLE_DEV_ENDPOINTS가 켜져 있습니다: /dev/... 개발용 충전 API가 열려 있습니다. 운영 환경에서는 꺼야 합니다.")
    # 결과를 모르는 타행 이체를 확인한다 (시작할 때 바로 돌아 재시작 복구도 겸한다). 키가 없으면 꺼 둔다
    worker = asyncio.create_task(interbank_worker()) if get_settings().interbank_enabled else None
    try:
        yield
    finally:
        if worker:
            worker.cancel()
        await engine.dispose()


app = FastAPI(title="AvengersBank", lifespan=lifespan, responses=error_responses(500))
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
register_exception_handlers(app)
app.add_exception_handler(HubRequestError, lambda request, exc: exc.response)
app.add_middleware(SignResponses)  # /interbank 응답에 응답 서명을 붙인다
app.include_router(user_router)
app.include_router(product_router)
app.include_router(account_router)
app.include_router(transfer_router)
app.include_router(interbank_router)
app.include_router(interbank_receiver_router)
app.include_router(notification_router)
app.include_router(card_router)
app.include_router(agent_router)
app.include_router(terms_router)
app.include_router(verification_router)
app.include_router(recovery_router)
app.include_router(money_router)
if get_settings().enable_dev_endpoints:
    app.include_router(dev_router)
    app.include_router(verification_dev_router)  # 문자함 읽기, 로그인 잠금 해제


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
