from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from avengers_bank.core.database import Base


class FavoriteAccount(Base):
    """자주 쓰는 이체 계좌 (이체 화면의 별표). 사용자별로 (은행, 계좌번호)가 한 번만 들어간다.

    bank_code가 ""이면 우리 은행이다(NULL을 쓰면 PostgreSQL이 NULL끼리를 다른 값으로 봐서 유니크가 깨진다).
    이름·은행 이름은 즐겨찾기 할 때의 값을 그대로 저장한다(표시용).
    """

    __tablename__ = "favorite_accounts"
    __table_args__ = (UniqueConstraint("user_id", "bank_code", "account", name="uq_favorite_accounts_user_bank_account"),)

    favorite_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False, index=True)
    bank_code: Mapped[str] = mapped_column(String(3), default="", nullable=False)
    bank_name: Mapped[str] = mapped_column(String(50), nullable=False)
    account: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
