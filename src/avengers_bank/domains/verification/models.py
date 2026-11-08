from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base

# 인증번호를 어디에 쓰나. CHECK 제약과 마이그레이션 8d9e0f1a2b3c가 같은 목록을 쓴다
PURPOSES = ("SIGNUP_PHONE", "CHANGE_PHONE", "PASSWORD_RESET", "FIND_LOGIN_ID", "ACCOUNT_PASSWORD_RESET", "WITHDRAWAL")


class VerificationCode(Base):
    """휴대폰 인증번호 1번 발송 = 행 1개.

    상태: 발송(verified_at NULL) → 확인 성공(verified_at) → 사용(consumed_at, 1회만).
    코드 원문은 저장하지 않고 HMAC만 둔다(service.py _code_hash). 발송 제한(번호당 15분 3번)도 이 행을 센다.
    """

    __tablename__ = "verification_codes"
    __table_args__ = (
        CheckConstraint(
            f"purpose IN ({', '.join(repr(p) for p in PURPOSES)})", name="ck_verification_codes_purpose"
        ),
        Index("ix_verification_codes_phone_purpose_created", "phone", "purpose", "created_at"),
    )

    verification_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    # 로그인한 사용자가 받은 인증(번호 변경 등)만 채운다. 가입 전에는 사용자가 없다
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.user_id"))
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
