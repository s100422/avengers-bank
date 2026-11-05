"""로그인 실패 횟수 제한 (비밀번호 무차별 대입 방지, C-040).

shortcut: 프로세스 메모리에서 센다. 서버를 재시작하면 초기화되고 서버가 여러 개면 각자 센다. 서비스로 쓸 때 Redis 등으로 바꾼다.
"""

import time

from avengers_bank.core.exceptions import ApiException

WINDOW_SECONDS = 15 * 60
MAX_FAILURES_PER_ID_AND_IP = 5  # 같은 아이디를 같은 IP에서 틀리는 횟수
MAX_FAILURES_PER_IP = 20  # 아이디를 바꿔 가며 찔러 보는 경우


class TooManyAttemptsException(ApiException):
    def __init__(self, retry_after: int):
        super().__init__(
            status_code=429, code="TOO_MANY_LOGIN_ATTEMPTS",
            message="로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.",
            headers={"Retry-After": str(retry_after)},
        )


class LoginLimiter:
    def __init__(self) -> None:
        self._failures: dict[tuple, list[float]] = {}

    def _recent(self, key: tuple, now: float) -> list[float]:
        recent = [t for t in self._failures.get(key, []) if now - t < WINDOW_SECONDS]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)  # 오래된 키를 치워서 메모리가 계속 늘지 않게 한다
        return recent

    def check(self, login_id: str, ip: str) -> None:
        """한도를 넘었으면 비밀번호 검증(argon2) 전에 거절한다."""
        now = time.monotonic()
        for key, limit in (((login_id, ip), MAX_FAILURES_PER_ID_AND_IP), ((ip,), MAX_FAILURES_PER_IP)):
            recent = self._recent(key, now)
            if len(recent) >= limit:
                raise TooManyAttemptsException(int(WINDOW_SECONDS - (now - recent[0])) + 1)

    def record_failure(self, login_id: str, ip: str) -> None:
        now = time.monotonic()
        for key in ((login_id, ip), (ip,)):
            self._failures.setdefault(key, []).append(now)

    def reset(self, login_id: str, ip: str) -> None:
        self._failures.pop((login_id, ip), None)  # 성공하면 그 아이디의 실패만 지운다

    def clear(self) -> None:
        self._failures.clear()


login_limiter = LoginLimiter()
