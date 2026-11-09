# ClearingHub 연동 서명 (SPEC 2.2, 2.5). Ed25519, 키·서명은 raw 바이트의 표준 base64.
import base64
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def _sign(private_key_b64: str, message: bytes) -> str:
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64))
    return base64.b64encode(key.sign(message)).decode()


def _verify(public_key_b64: str, message: bytes, signature_b64: str) -> bool:
    try:  # 키·서명이 base64가 아니거나 길이가 틀려도 예외(500) 대신 False(401)
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64, validate=True))
        key.verify(base64.b64decode(signature_b64, validate=True), message)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def _fresh(ts: str | None, skew: int = 300) -> bool:  # 시각 차이 5분 (2.2)
    try:
        return abs(int(time.time()) - int(ts)) <= skew
    except (ValueError, TypeError):
        return False


def sign_request(private_key_b64: str, method: str, path: str, body: bytes, ts: str | None = None) -> dict[str, str]:
    """요청 서명. path: 은행→허브는 /v1부터, 허브→은행은 base_url 뒤 부분. body: 보내는 바이트 그대로."""
    ts = ts or str(int(time.time()))
    msg = f"{ts}\n{method.upper()}\n{path}\n".encode() + body
    return {"X-Timestamp": ts, "X-Signature": _sign(private_key_b64, msg), "X-Signature-Alg": "ed25519"}


def verify_request(public_key_b64: str, ts: str | None, method: str, path: str, body: bytes, signature: str | None) -> bool:
    return _fresh(ts) and _verify(public_key_b64, f"{ts}\n{method.upper()}\n{path}\n".encode() + body, signature or "")


def sign_response(private_key_b64: str, status: int, request_signature: str, body: bytes,
                  ts: str | None = None) -> dict[str, str]:
    """응답 서명. request_signature: 그 요청의 X-Signature 그대로(없었으면 ""). body: 보내는 바이트 그대로."""
    ts = ts or str(int(time.time()))
    msg = f"{ts}\n{status}\n{request_signature}\n".encode() + body
    return {"X-Response-Timestamp": ts, "X-Response-Signature": _sign(private_key_b64, msg), "X-Signature-Alg": "ed25519"}


def verify_response(public_key_b64: str, ts: str | None, status: int, request_signature: str, body: bytes,
                    signature: str | None) -> bool:
    return _fresh(ts) and _verify(public_key_b64, f"{ts}\n{status}\n{request_signature}\n".encode() + body, signature or "")
