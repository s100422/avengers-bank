"""결과를 모르는 타행 이체(PENDING)를 확인한다 (SPEC 6절 4-1, 5). 서버가 시작될 때 바로 한 번 돌아서
재시작 복구(5)도 겸한다.

shortcut: 30분이 지나도 30초 간격으로 계속 묻는다(SPEC은 10분으로 늦추라 함), 프로세스 1개 전제(Dockerfile의 워커 1개).
거래가 많아지거나 워커를 늘리면 늦춤 규칙과 행 잠금(SKIP LOCKED)을 더한다.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from avengers_bank.core.database import SessionLocal
from avengers_bank.domains.interbank.hub_client import HubUnreachable, hub_call
from avengers_bank.domains.interbank.models import InterbankTransfer
from avengers_bank.domains.interbank.service import interbank_service

logger = logging.getLogger(__name__)
INTERVAL = 30  # 초
RESEND_AFTER = timedelta(minutes=1)  # 마지막 POST 뒤 1분이 지난 404일 때만 다시 보낸다 (SPEC 3.4)
RECENT = timedelta(seconds=20)  # 방금 보낸 거래는 요청 처리 쪽이 아직 결과를 기다리는 중이다


async def reconcile_once() -> None:
    async with SessionLocal() as db:
        async with db.begin():
            rows = (await db.execute(
                select(InterbankTransfer.transfer_id, InterbankTransfer.last_sent_at, InterbankTransfer.created_at)
                .where(InterbankTransfer.direction == "OUT", InterbankTransfer.status == "PENDING")
            )).all()
    now = datetime.now(timezone.utc)
    for transfer_id, last_sent_at, created_at in rows:
        sent = last_sent_at or created_at
        sent = sent if sent.tzinfo else sent.replace(tzinfo=timezone.utc)  # SQLite는 시간대 없이 돌려준다
        if now - sent < RECENT:
            continue
        async with SessionLocal() as db:
            try:
                reply = await hub_call("GET", f"/v1/transfers/{transfer_id}")
                if reply.verified and reply.status == 404 and reply.body.get("error") == "TRANSFER_NOT_FOUND":
                    # 접수 기록이 없다: 되돌리지 않고 같은 ID로 다시 보낸다 (멱등)
                    if now - sent >= RESEND_AFTER:
                        await interbank_service.deliver(db, transfer_id)
                else:
                    await interbank_service.apply(db, transfer_id, reply)
            except HubUnreachable:
                continue


async def run_forever() -> None:
    while True:
        try:
            await reconcile_once()
        except Exception:  # 한 번 실패해도 작업은 계속 돈다
            logger.exception("타행 이체 확인 작업 실패")
        await asyncio.sleep(INTERVAL)
