"""IP 단위 시도 횟수 제한 (C-040). 로그인 실패와 인증번호 발송이 같은 방식을 쓴다.

같은 아이디를 계속 틀리는 경우는 여기서 막지 않는다: users 테이블의 DB 카운터가 5회 연속 실패면 그 아이디를
잠근다(C-090, users/service.py login). 예전의 '아이디+IP 5회'(C-082)와 '아이디별 느리게'(C-089)는 그것으로 대체했다.
여기 남은 것은 아이디를 바꿔 가며 찔러 보는 공격(아이디 하나당 몇 번씩, 많은 아이디)을 막는 IP 한도뿐이다.

shortcut: 프로세스 메모리에서 센다. 서버를 재시작하면 초기화되고 서버가 여러 개면 각자 센다. 서비스로 쓸 때 Redis 등으로 바꾼다.
"""

import time

from avengers_bank.core.exceptions import ApiException

WINDOW_SECONDS = 15 * 60
MAX_LOGIN_FAILURES_PER_IP = 20  # 아이디를 바꿔 가며 찔러 보는 경우
MAX_VERIFICATION_SENDS_PER_IP = 10  # 여러 번호로 문자를 보내 비용을 쓰게 하는 경우


class TooManyAttemptsException(ApiException):
    def __init__(self, retry_after: int, code: str, message: str):
        super().__init__(status_code=429, code=code, message=message, headers={"Retry-After": str(retry_after)})


class IpLimiter:
    def __init__(self, limit: int, code: str, message: str) -> None:
        self.limit, self.code, self.message = limit, code, message
        self._attempts: dict[str, list[float]] = {}

    def acquire(self, ip: str) -> float:
        """한도를 확인하고, 통과하면 일(비밀번호 검증·문자 발송)을 하기 *전에* 시도 1회를 미리 기록한다. 반환값은 이 시도의 기록.

        예전에는 check → 검증(await, 약 70ms) → 실패하면 기록 순서였다. 그러면 동시에 들어온 요청 30개가
        모두 check를 통과한 뒤에야 기록되어 30번 검증됐다(한도 무력화). 그래서 확인과 기록을 붙였다.
        이 메서드 안에는 await가 없다: asyncio는 스레드 하나에서 await 지점에서만 다른 요청으로 넘어가므로,
        await 없는 코드는 중간에 끼어들 틈이 없어 그 자체로 원자적이다 (락 불필요. 워커 1개 전제 — 모듈 주석 참고).
        """
        now = time.monotonic()
        recent = [t for t in self._attempts.get(ip, []) if now - t < WINDOW_SECONDS]
        if len(recent) >= self.limit:
            self._attempts[ip] = recent
            raise TooManyAttemptsException(int(WINDOW_SECONDS - (now - recent[0])) + 1, self.code, self.message)
        recent.append(now)
        self._attempts[ip] = recent  # 창 밖 기록은 여기서 버려진다 (메모리가 계속 늘지 않게)
        return now

    def reset(self, ip: str, attempt: float) -> None:
        """성공한 시도는 실패로 치지 않는다: 이번 시도 한 건만 뺀다.

        같은 IP의 다른 기록(다른 아이디로 틀린 것)은 남긴다. 성공 한 번으로 IP 단위 대입 기록이 지워지면 안 된다.
        """
        try:
            self._attempts[ip].remove(attempt)
        except (KeyError, ValueError):
            pass  # 그사이 창(15분) 밖으로 밀려 이미 지워졌다

    def clear(self) -> None:
        self._attempts.clear()


login_limiter = IpLimiter(
    MAX_LOGIN_FAILURES_PER_IP, "TOO_MANY_LOGIN_ATTEMPTS", "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요."
)
verification_ip_limiter = IpLimiter(
    MAX_VERIFICATION_SENDS_PER_IP, "TOO_MANY_VERIFICATION_REQUESTS", "인증번호 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."
)
