from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class InterbankTransfer(Base):
    """타행 이체 기록 (SPEC 4.2, 6절). 보낸 것(OUT)과 받은 것(IN)을 한 표에 둔다.

    transfer_id가 기본키라 같은 ID는 한 번만 들어간다: 받는 쪽 멱등성의 근거 (SPEC 4.2 규칙 1·2).
    OUT의 PENDING 행이 곧 '중간 계정'이다: 돈은 이미 고객 계좌에서 나갔고 결과를 기다린다.
    """

    __tablename__ = "interbank_transfers"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_interbank_transfers_amount_positive"),
        CheckConstraint("direction IN ('OUT', 'IN')", name="ck_interbank_transfers_direction"),
        CheckConstraint("status IN ('PENDING', 'COMPLETED', 'FAILED')", name="ck_interbank_transfers_status"),
        Index("ix_interbank_transfers_status", "status"),
    )

    transfer_id: Mapped[str] = mapped_column(String(36), primary_key=True)  # 소문자 UUID v4
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    checking_account_id: Mapped[int] = mapped_column(
        ForeignKey("checking_accounts.checking_account_id"), nullable=False, index=True
    )
    peer_bank: Mapped[str] = mapped_column(String(3), nullable=False)  # 상대 은행 코드
    peer_bank_name: Mapped[str | None] = mapped_column(String(50))
    peer_account: Mapped[str] = mapped_column(String(50), nullable=False)
    peer_name: Mapped[str | None] = mapped_column(String(100))  # OUT: 받는 분(허브가 알려 준 예금주), IN: 보낸 분
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    memo: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    fail_code: Mapped[str | None] = mapped_column(String(40))
    fail_message: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 마지막 POST 시각 (SPEC 3.4: 404 뒤 1분 규칙)
