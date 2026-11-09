"""ClearingHub 호출 (SPEC 3절). 서명해서 보내고, 허브 응답 서명을 검증한다 (2.5)."""
import json
from dataclasses import dataclass

import httpx

from avengers_bank.core.config import get_settings
from avengers_bank.domains.interbank.signing import sign_request, verify_response

_transport: httpx.AsyncBaseTransport | None = None  # 테스트가 가짜 허브를 끼운다


class HubUnreachable(Exception):
    """연결 실패·타임아웃. 결과를 모르는 상태다."""


@dataclass
class HubReply:
    status: int
    body: dict
    verified: bool  # 응답 서명이 허브 공개키로 맞는가. 아니면 본문을 믿지 않는다 (SPEC 2.5)


async def hub_call(method: str, path: str, payload: dict | None = None) -> HubReply:
    """path는 /v1부터. 본문은 서명한 바이트 그대로 보낸다."""
    s = get_settings()
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode() if payload is not None else b""
    signed = sign_request(s.bank_private_key.get_secret_value(), method, path, body)
    headers = {
        "X-Bank-Code": s.bank_code, "X-Api-Key": s.bank_api_key.get_secret_value(),
        "Content-Type": "application/json", **signed,
    }
    try:
        async with httpx.AsyncClient(transport=_transport, timeout=10) as client:
            res = await client.request(method, s.hub_url.rstrip("/") + path, content=body, headers=headers)
    except httpx.HTTPError as exc:
        raise HubUnreachable(str(exc)) from exc
    verified = verify_response(
        s.hub_public_key, res.headers.get("x-response-timestamp"), res.status_code,
        signed["X-Signature"], res.content, res.headers.get("x-response-signature"),
    )
    try:
        parsed = json.loads(res.content)
    except ValueError:  # 5xx는 본문 형식을 보장하지 않는다 (SPEC 5절)
        parsed = {}
    return HubReply(res.status_code, parsed if isinstance(parsed, dict) else {}, verified)
