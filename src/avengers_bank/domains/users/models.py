from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    login_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    nick_name: Mapped[str | None] = mapped_column(String(50))
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 휴대폰 인증번호로 확인한 시각 (가입·번호 변경 때 채운다). 이 컬럼이 생기기 전 가입자는 NULL
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 로그인 잠금 (C-090): 비밀번호를 연속으로 틀린 횟수. 맞히면 0. 5가 되면 login_locked_at을 채운다
    failed_login_count: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0", nullable=False)
    # 잠긴 시각. 잠기면 맞는 비밀번호도 거절한다. 해제는 본인 확인(비밀번호 찾기, 2단계)·관리자 명령(admin.py)으로만
    login_locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 회원 탈퇴 시각 (users/withdrawal.py). 행은 지우지 않는다(소프트 삭제): 계좌·거래내역·약관 동의 기록이 이 행을
    # 가리키고, login_id를 남겨 같은 아이디 재가입을 막는다. 탈퇴하면 이름·전화번호 등은 가린다
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# refresh_tokens.revoked_reason에 들어갈 수 있는 값 (CHECK 제약과 마이그레이션 8d9e0f1a2b3c가 같은 목록을 쓴다)
REVOKED_REASONS = ("ROTATED", "LOGOUT", "LOGOUT_ALL", "PASSWORD_CHANGED", "REUSE_DETECTED", "LOGIN_ELSEWHERE", "WITHDRAWN")


class RefreshToken(Base):
    """갱신 토큰 1개 = 행 1개. 원문은 저장하지 않고 SHA-256 해시만 둔다 (core/security.py).

    family_id: 로그인 1번 = family 1개 = 세션 1개. 갱신할 때마다 같은 family 안에서 새 행이 생기고
    이전 행은 revoked_at + replaced_by_id(다음 행)가 채워진다. 그래서 "교체된 토큰이 또 왔다"를 알아내
    탈취로 보고 family 전체를 끊을 수 있다(재사용 감지). 로그아웃도 family 단위로 끊는다.
    만료·폐기된 행은 지금은 쌓이기만 한다 — 추후 정리 작업(예: 만료 후 N일 지난 행 삭제)이 필요하다.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        # 교체된 토큰은 반드시 폐기 상태여야 한다 (재사용 감지가 이 둘을 함께 본다)
        CheckConstraint("replaced_by_id IS NULL OR revoked_at IS NOT NULL", name="ck_refresh_tokens_replaced_is_revoked"),
        CheckConstraint(
            f"revoked_reason IS NULL OR revoked_reason IN ({', '.join(repr(r) for r in REVOKED_REASONS)})",
            name="ck_refresh_tokens_revoked_reason",
        ),
        # 이유는 폐기된 행에만 있다. 반대(폐기됐는데 이유 NULL)는 허용: 이 컬럼이 생기기 전에 폐기된 행
        CheckConstraint("revoked_reason IS NULL OR revoked_at IS NOT NULL", name="ck_refresh_tokens_reason_is_revoked"),
    )

    refresh_token_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), index=True, nullable=False)
    family_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[int | None] = mapped_column(ForeignKey("refresh_tokens.refresh_token_id"))
    # 왜 끊겼나. 끊긴 기기에 "다른 곳에서 로그인되어 로그아웃되었습니다."를 보여 주려면(LOGIN_ELSEWHERE) 필요하다
    revoked_reason: Mapped[str | None] = mapped_column(String(20))
