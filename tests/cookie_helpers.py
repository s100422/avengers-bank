"""갱신 토큰은 본문이 아니라 쿠키로 오간다. 테스트는 Set-Cookie에서 원문을 꺼내고, 요청에는 Cookie 헤더를 직접 실어 보낸다.

헤더를 직접 싣는 이유: 한 클라이언트(쿠키 보관함 하나)로 기기 여러 대를 흉내 내기 위해서다.
Cookie 헤더를 직접 주면 httpx는 보관함의 쿠키를 붙이지 않는다.
"""

from http.cookies import SimpleCookie


def set_cookies(response) -> dict:
    """응답의 Set-Cookie를 {이름: Morsel}로. 지우는 쿠키(Max-Age=0)도 그대로 들어 있다."""
    jar = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        jar.load(header)
    return dict(jar)


def cookie_value(response, name: str = "refresh_token") -> str | None:
    morsel = set_cookies(response).get(name)
    return morsel.value if morsel else None


def session_of(response) -> dict:
    """응답 본문 + 쿠키의 갱신 토큰을 합친 dict. 예전 본문(refresh_token 포함)처럼 쓰는 테스트가 많아 그 모양을 되살린다."""
    data = response.json()["data"]
    return {**data, "refresh_token": cookie_value(response)}


def cookie_header(refresh_token: str | None = None, device_token: str | None = None) -> dict[str, str]:
    parts = []
    if refresh_token is not None:
        parts.append(f"refresh_token={refresh_token}")
    if device_token is not None:
        parts.append(f"device_token={device_token}")
    return {"Cookie": "; ".join(parts)}


async def refresh(client, token):
    return await client.post("/users/token/refresh", headers=cookie_header(token))


async def logout(client, token):
    return await client.post("/users/logout", headers=cookie_header(token))
