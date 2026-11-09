import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from avengers_bank.core.exceptions import ApiException
from avengers_bank.core.responses import ErrorDetail, ErrorResponse, ValidationIssue

logger = logging.getLogger(__name__)


async def api_exception_handler(request: Request, exc: ApiException) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=exc.code, message=exc.message))
    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(mode="json"),
        headers=exc.headers,
    )


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        422: "VALIDATION_ERROR",
    }.get(exc.status_code, "HTTP_ERROR")
    message = exc.detail if isinstance(exc.detail, str) else "요청을 처리할 수 없습니다."
    return await api_exception_handler(
        request, ApiException(exc.status_code, code, message, headers=exc.headers)
    )


# 422 details[].msg 를 한국어 완성 문장으로 바꿀 때 쓰는 필드 이름표. 없는 필드는 "입력값"으로 부른다.
FIELD_LABELS = {
    "login_id": "아이디", "password": "비밀번호", "new_password": "새 비밀번호",
    "current_password": "현재 비밀번호", "refresh_token": "갱신 토큰", "name": "이름", "nick_name": "닉네임",
    "phone": "휴대폰 번호", "user_id": "회원 번호", "amount": "금액", "initial_amount": "가입 금액",
    "monthly_payment": "매월 납입액", "monthly_deposit_date": "매월 납입일", "maturity_date": "만기일",
    "nickname": "계좌 별명", "product_id": "상품", "account_type": "계좌 종류", "types": "계좌 종류",
    "account_id": "계좌", "checking_account_id": "입출금 계좌", "from_checking_account_id": "출금 계좌",
    "to_checking_account_id": "입금 계좌", "to_account_num": "받는 계좌번호", "recipient_name": "받는 분 이름",
    "counterpart_name": "상대방 이름", "daily_transfer_limit": "1일 이체 한도", "per_transfer_limit": "1회 이체 한도",
    "card_type": "카드 종류", "card_id": "카드", "credit_limit": "신용 한도", "payment_date": "결제일",
    "place_of_use": "사용처", "year_month": "조회 연월", "date_from": "조회 시작일", "date_to": "조회 종료일",
    "min_amount": "최소 금액", "max_amount": "최대 금액", "q": "검색어", "limit": "조회 개수", "offset": "조회 시작 위치",
    "status": "상태", "action": "요청 동작", "draft_id": "이체 요청", "message": "메시지", "conversation_id": "대화",
    "agreements": "약관 동의", "agreed": "약관 동의 여부", "terms_version_id": "약관", "revision_id": "약관 개정본",
    "set_hash": "약관 묶음", "consent": "약관 동의",
    "phone_verification_token": "휴대폰 인증", "verification_id": "인증 요청", "code": "인증번호", "purpose": "인증 용도",
    "account_password": "계좌 비밀번호", "from_account_password": "출금 계좌 비밀번호",
    "account_num": "계좌번호", "recovery_token": "본인 확인 요청", "reset_token": "비밀번호 재설정 요청",
    "new_account_password": "새 계좌 비밀번호", "challenge_token": "기기 확인",
}


def _josa(word: str, with_batchim: str, without: str) -> str:
    """받침이 있으면 앞의 조사(을/은/이), 없으면 뒤의 조사(를/는/가)."""
    last = word[-1]
    has_batchim = "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 != 0
    return word + (with_batchim if has_batchim else without)


def _number(value) -> str:
    return f"{value:,}" if isinstance(value, int) else str(value)


def korean_message(error: dict) -> str:
    """pydantic 오류 하나를 사용자에게 보여 줄 한국어 문장으로 바꾼다."""
    kind, ctx = error["type"], error.get("ctx") or {}
    label = next((FIELD_LABELS[p] for p in reversed(error["loc"]) if isinstance(p, str) and p in FIELD_LABELS), "입력값")
    topic = _josa(label, "은", "는")  # "이름은", "아이디는"
    if kind == "value_error":  # 검증기에서 직접 낸 메시지는 처음부터 한국어 문장이다
        return error["msg"].removeprefix("Value error, ")
    if kind == "missing":
        return f"필수 항목입니다: {label}"
    if kind == "extra_forbidden":
        return f"변경할 수 없는 항목입니다: {label}"
    if kind == "string_too_short":
        if ctx.get("min_length") == 1:
            return f"{_josa(label, '을', '를')} 입력해 주세요."
        return f"{topic} {ctx.get('min_length')}자 이상 입력해 주세요."
    if kind == "json_invalid":
        return "요청 본문이 올바른 JSON 형식이 아닙니다."
    templates = {
        "string_too_long": "{topic} {max_length}자 이하로 입력해 주세요.",
        "too_short": "{topic} {min_length}개 이상 보내 주세요.",
        "too_long": "{topic} {max_length}개 이하로 보내 주세요.",
        "greater_than": "{topic} {gt}보다 커야 합니다.",
        "greater_than_equal": "{topic} {ge} 이상이어야 합니다.",
        "less_than": "{topic} {lt}보다 작아야 합니다.",
        "less_than_equal": "{topic} {le} 이하여야 합니다.",
        "int_parsing": "{topic} 정수로 입력해 주세요.",
        "int_type": "{topic} 정수로 입력해 주세요.",
        "int_from_float": "{topic} 정수로 입력해 주세요.",
        "string_type": "{topic} 문자열로 입력해 주세요.",
        "bool_parsing": "{topic} true 또는 false로 입력해 주세요.",
        "bool_type": "{topic} true 또는 false로 입력해 주세요.",
        "date_parsing": "{topic} YYYY-MM-DD 형식의 날짜로 입력해 주세요.",
        "date_type": "{topic} YYYY-MM-DD 형식의 날짜로 입력해 주세요.",
        "date_from_datetime_parsing": "{topic} YYYY-MM-DD 형식의 날짜로 입력해 주세요.",
        "date_from_datetime_inexact": "{topic} YYYY-MM-DD 형식의 날짜로 입력해 주세요.",
        "literal_error": "{topic} 허용된 값 중 하나로 입력해 주세요.",
        "enum": "{topic} 허용된 값 중 하나로 입력해 주세요.",
        "string_pattern_mismatch": "{topic} 형식이 올바르지 않습니다.",
        "model_attributes_type": "요청 본문 형식이 올바르지 않습니다.",
        "dict_type": "요청 본문 형식이 올바르지 않습니다.",
        "list_type": "{topic} 목록 형식으로 보내 주세요.",
    }
    if kind not in templates:
        return f"입력값을 확인해 주세요: {label}"
    return templates[kind].format(topic=topic, **{k: _number(v) for k, v in ctx.items()})


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = [
        ValidationIssue(loc=list(error["loc"]), msg=korean_message(error), type=error["type"])
        for error in exc.errors()
    ]
    body = ErrorResponse(
        error=ErrorDetail(
            code="VALIDATION_ERROR", message="입력값을 확인해 주세요.", details=details
        )
    )
    return JSONResponse(status_code=422, content=body.model_dump(mode="json"))


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("처리하지 못한 요청 오류: %s %s", request.method, request.url.path, exc_info=exc)
    return await api_exception_handler(
        request, ApiException(500, "INTERNAL_SERVER_ERROR", "서버에서 오류가 발생했습니다.")
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiException, api_exception_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
