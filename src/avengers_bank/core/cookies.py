"""갱신 토큰·기기 토큰 쿠키와 그 쿠키를 쓰는 요청의 CSRF 확인.

둘 다 httpOnly(JS가 못 읽음 → XSS가 생겨도 토큰을 못 훔친다) + SameSite=Strict(다른 사이트에서 시작한 요청엔 안 실림)다.
SameSite만 믿지 않고 Origin도 확인한다: 같은 사이트의 다른 서브도메인 등 SameSite가 막지 못하는 경로를 위한 2차 방어.
"""

from fastapi import Request, Response

from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import ForbiddenException

REFRESH_COOKIE = "refresh_token"
DEVICE_COOKIE = "device_token"


def require_allowed_origin(request: Request) -> None:
    """쿠키로 인증하는 POST/DELETE 의존성. Origin이 CORS 허용 목록에 없거나 없으면 403 CSRF_ORIGIN.

    브라우저는 POST·DELETE에 항상 Origin을 보내고(Next 프록시도 그대로 전달), 다른 사이트 폼·스크립트는 자기 Origin이 실린다.
    Origin을 보내지 않는 클라이언트(curl 등)는 쿠키를 직접 만들어 보낼 수 있으니 CSRF 대상이 아니지만, 구분할 수 없으므로 같이 막는다.
    """
    origin = request.headers.get("origin")
    if not origin or origin not in get_settings().cors_origin_list:
        raise ForbiddenException(message="허용되지 않은 요청 출처입니다.", code="CSRF_ORIGIN")


def set_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    settings = get_settings()
    response.set_cookie(
        name, value, max_age=max_age, path=settings.refresh_cookie_path,
        secure=settings.cookie_secure, httponly=True, samesite="strict",
    )


def clear_cookie(response: Response, name: str) -> None:
    """Max-Age=0 (지울 때도 만들 때와 같은 path·속성이어야 브라우저가 같은 쿠키로 알아본다)."""
    settings = get_settings()
    response.delete_cookie(
        name, path=settings.refresh_cookie_path, secure=settings.cookie_secure, httponly=True, samesite="strict"
    )


def set_refresh_cookie(response: Response, raw_token: str) -> None:
    # 수명 = 세션 수명(슬라이딩이라 갱신할 때마다 다시 이 값으로 새로 내려간다)
    set_cookie(response, REFRESH_COOKIE, raw_token, get_settings().session_expire_minutes * 60)


def set_device_cookie(response: Response, raw_token: str) -> None:
    set_cookie(response, DEVICE_COOKIE, raw_token, get_settings().device_cookie_days * 86400)


def clear_cookie_header(name: str) -> str:
    """오류 응답(예외)에 실어 보낼 Set-Cookie 값. 예외는 응답 객체를 못 만지므로 임시 응답에서 뽑는다."""
    tmp = Response()
    clear_cookie(tmp, name)
    return tmp.headers["set-cookie"]
