"""문자 발송. 실제 문자 업체가 정해지면 send_sms 하나만 바꾸면 된다.

지금은 개발용 발송기뿐이다: 서버 로그에 찍고 메모리 '문자함'에 쌓는다(GET /dev/sms로 읽는다).
설정 SMS_SENDER는 "dev"만 받는다(config.py, 다른 값이면 서버가 시작되지 않는다) — 실제 발송 없이 운영에 나가는 것을 막는다.
"""

import logging
from collections import deque
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# 최근 문자 (번호, 내용, 보낸 시각). 개발용이라 오래된 것부터 버려 메모리를 묶어 둔다
dev_inbox: deque[tuple[str, str, datetime]] = deque(maxlen=1000)


async def send_sms(phone: str, text: str) -> None:
    logger.warning("[개발용 문자] %s: %s", phone, text)
    dev_inbox.append((phone, text, datetime.now(timezone.utc)))


def dev_messages(phone: str, limit: int = 20) -> list[tuple[str, datetime]]:
    """그 번호로 보낸 최근 문자 (최신순)."""
    return [(text, at) for p, text, at in reversed(dev_inbox) if p == phone][:limit]
