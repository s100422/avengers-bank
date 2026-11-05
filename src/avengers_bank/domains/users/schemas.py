from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UserCreate(BaseModel):
    login_id: str = Field(min_length=4, max_length=50)
    password: str = Field(min_length=8, max_length=128, repr=False)
    name: str = Field(min_length=1, max_length=50)
    nick_name: str | None = Field(default=None, max_length=50)
    phone: str = Field(min_length=9, max_length=20)


class UserLogin(BaseModel):
    login_id: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128, repr=False)


class UserUpdate(BaseModel):
    """PATCH /users/me: 보낸 필드만 바꾼다. nick_name에 null을 보내면 닉네임을 지운다."""

    model_config = ConfigDict(extra="forbid")  # login_id·password처럼 바꿀 수 없는 필드는 422로 알려 준다

    name: str | None = Field(default=None, min_length=1, max_length=50)
    nick_name: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, min_length=9, max_length=20)

    @model_validator(mode="after")
    def _required_fields_not_null(self):
        for field in ("name", "phone"):  # 가입 때 필수였던 값은 비울 수 없다
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field}은(는) 비울 수 없습니다.")
        return self


class UserResponse(BaseModel):
    user_id: int
    login_id: str
    name: str
    nick_name: str | None
    phone: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
