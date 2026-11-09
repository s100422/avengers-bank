"""허브가 부르는 API (받는 쪽, SPEC 4절). 로그인 쿠키가 아니라 허브의 Ed25519 서명으로 인증한다.

응답 형식이 이 프로젝트의 {"error": {...}}와 달라서(SPEC 5절: {"error": CODE, "message": ...}) 이 경로는
JSONResponse를 직접 돌려주고, 응답 서명은 SignResponses 미들웨어가 붙인다 (main.py).
"""
import json
import re
import uuid
from datetime import timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.config import get_settings
from avengers_bank.core.database import get_db
from avengers_bank.domains.accounts.kinds import INTERBANK_IN
from avengers_bank.domains.accounts.models import CheckingAccount, CheckingAccountHistory
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.interbank.models import InterbankTransfer
from avengers_bank.domains.interbank.signing import sign_response, verify_request
from avengers_bank.domains.users.models import User

PREFIX = "/interbank"  # 등록하는 base_url의 경로 부분 (https://도메인/interbank)
router = APIRouter(prefix=PREFIX, include_in_schema=False)
DbSession = Annotated[AsyncSession, Depends(get_db)]


class HubRequestError(Exception):
    def __init__(self, response: JSONResponse):
        self.response = response


def error(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse({"error": code, "message": message, **extra}, status_code=status)


class SignResponses:
    """순수 ASGI 미들웨어: /interbank의 2xx·4xx 응답 본문 바이트에 응답 서명을 붙인다 (SPEC 2.5).
    서명 검증 실패 401에도 붙는다. 5xx는 서명하지 않는다 (허브가 5xx는 본문과 상관없이 재시도한다)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        settings = get_settings()
        if scope["type"] != "http" or not scope["path"].startswith(PREFIX) or not settings.receiver_enabled:
            return await self.app(scope, receive, send)
        request_signature, start = dict(scope["headers"]).get(b"x-signature", b"").decode(), {}

        async def send_signed(message):
            if message["type"] == "http.response.start":
                return start.update(message)  # 본문을 볼 때까지 미룬다
            if start:
                if start["status"] < 500:
                    signed = sign_response(
                        settings.bank_private_key.get_secret_value(), start["status"], request_signature,
                        message.get("body", b""),
                    )
                    start["headers"] = [*start["headers"], *((k.lower().encode(), v.encode()) for k, v in signed.items())]
                await send(start)
                start.clear()
            await send(message)

        await self.app(scope, receive, send_signed)


async def hub_json(request: Request) -> dict:
    """허브 서명 검증 (SPEC 2.2): 원본 바이트·허브 공개키·PATH는 base_url 뒤 부분. 입금 처리보다 먼저 한다."""
    s = get_settings()
    if not s.receiver_enabled:
        raise HubRequestError(error(503, "INTERBANK_DISABLED", "타행 이체를 사용할 수 없습니다."))
    body, h = await request.body(), request.headers
    path = request.url.path.partition(PREFIX)[2]  # /interbank/receive → /receive
    if (h.get("x-bank-code") != "000" or h.get("x-signature-alg", "ed25519") != "ed25519"
            or not verify_request(s.hub_public_key, h.get("x-timestamp"), request.method, path, body, h.get("x-signature"))):
        raise HubRequestError(error(401, "SIGNATURE_INVALID", "서명이 맞지 않습니다"))
    try:
        data = json.loads(body) if body else {}
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise HubRequestError(error(422, "VALIDATION_ERROR", "본문이 JSON 객체가 아닙니다"))
    return data


def _text(data: dict, field: str, max_len: int, required: bool = True) -> str | None:
    value = data.get(field, None if required else "")
    if not isinstance(value, str) or (required and not value) or len(value) > max_len:
        raise HubRequestError(error(422, "VALIDATION_ERROR", f"{field} 형식이 올바르지 않습니다"))
    return value


def _valid_receive(data: dict) -> dict:
    tid = _text(data, "transfer_id", 36)
    try:
        if str(uuid.UUID(tid)) != tid:
            raise ValueError
    except ValueError:
        raise HubRequestError(error(422, "VALIDATION_ERROR", "transfer_id 형식이 올바르지 않습니다")) from None
    bank = _text(data, "from_bank", 3)
    amount = data.get("amount")
    if not re.fullmatch(r"\d{3}", bank) or isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise HubRequestError(error(422, "VALIDATION_ERROR", "from_bank 또는 amount 형식이 올바르지 않습니다"))
    return {
        "transfer_id": tid, "from_bank": bank, "from_bank_name": _text(data, "from_bank_name", 50, False) or None,
        "from_account": _text(data, "from_account", 50), "to_account": _text(data, "to_account", 50),
        "amount": amount, "sender_name": _text(data, "sender_name", 50), "memo": _text(data, "memo", 100, False),
    }


async def _holder_name(db: AsyncSession, user_id: int) -> str:
    return (await db.get(User, user_id)).name


@router.post("/inquiry")
async def inquiry(request: Request, db: DbSession):
    data = await hub_json(request)
    account_num = _text(data, "account_num", 50)
    async with db.begin():
        account = await account_repository.find_checking_by_account_num(db, account_num)  # 닫힌 계좌는 없는 계좌
        if account is None:
            return error(404, "ACCOUNT_NOT_FOUND", "받는 계좌를 찾을 수 없습니다")
        return {"holder_name": await _holder_name(db, account.user_id)}


@router.post("/receive")
async def receive(request: Request, db: DbSession):
    data = _valid_receive(await hub_json(request))
    tid = data["transfer_id"]
    try:
        async with db.begin():
            existing = await db.get(InterbankTransfer, tid)
            if existing is not None:  # 같은 ID가 다시 오면 입금하지 않고 같은 답 (SPEC 4.2 규칙 1)
                return await _completed(db, existing)
            account = await account_repository.find_checking_by_account_num(db, data["to_account"])
            if account is None:  # 거절은 4xx, 기록하지 않는다 (규칙 5)
                return error(404, "ACCOUNT_NOT_FOUND", "받는 계좌를 찾을 수 없습니다", transfer_id=tid)
            (account,) = await account_repository.lock_checking_accounts(db, [account.checking_account_id])
            if account.closed_at is not None:  # 잠근 뒤 확인: 방금 탈퇴했으면 없는 계좌와 같다
                return error(404, "ACCOUNT_NOT_FOUND", "받는 계좌를 찾을 수 없습니다", transfer_id=tid)
            account.balance += data["amount"]
            # 입금 기록과 transfer_id 저장은 한 트랜잭션 (규칙 2). 같은 ID가 동시에 오면 PK에 걸려 롤백된다
            row = InterbankTransfer(
                transfer_id=tid, direction="IN", checking_account_id=account.checking_account_id,
                peer_bank=data["from_bank"], peer_bank_name=data["from_bank_name"], peer_account=data["from_account"],
                peer_name=data["sender_name"], amount=data["amount"], memo=data["memo"] or "", status="COMPLETED",
            )
            db.add(row)
            await account_repository.save_history(db, CheckingAccountHistory(
                checking_account_id=account.checking_account_id, amount=data["amount"], balance_after=account.balance,
                type=INTERBANK_IN, counterpart_account=data["from_account"], counterpart_name=data["sender_name"],  # 이름만(은행 이름은 넣지 않는다: 화면 표시를 통일하려는 결정, C-108)
            ))
            await db.flush()
            return await _completed(db, row)
    except IntegrityError:
        # 동시에 온 같은 ID. 절대 4xx로 답하지 않는다 (이중 지급): 저장된 결과를 읽어 200, 못 읽으면 503 (규칙 2)
        async with db.begin():
            existing = await db.get(InterbankTransfer, tid, populate_existing=True)
            if existing is not None:
                return await _completed(db, existing)
        return JSONResponse({"error": "INTERNAL_ERROR", "message": "잠시 후 다시 시도해 주세요"}, status_code=503)


@router.get("/receive/{transfer_id}")
async def receive_status(transfer_id: str, request: Request, db: DbSession):
    await hub_json(request)
    async with db.begin():
        row = await db.get(InterbankTransfer, transfer_id)
        if row is None or row.direction != "IN":  # 입금하지 않은 거래는 모두 404 (SPEC 4.3)
            return error(404, "TRANSFER_NOT_FOUND", "그 거래 ID로 입금한 적이 없습니다", transfer_id=transfer_id)
        return await _completed(db, row, received_at=True)


async def _completed(db: AsyncSession, row: InterbankTransfer, received_at: bool = False) -> dict:
    account = await db.get(CheckingAccount, row.checking_account_id)
    body = {"transfer_id": row.transfer_id, "status": "COMPLETED", "holder_name": await _holder_name(db, account.user_id)}
    if received_at:
        created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc)
        body["received_at"] = created.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return body
