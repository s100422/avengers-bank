from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from avengers_bank.domains.users.validators import (
    ChangedPassword,
    LoginId,
    Name,
    NewPassword,
    NickName,
    Phone,
    normalize_login_id,
)


class UserCreate(BaseModel):
    login_id: LoginId  # 앞뒤 공백 제거·소문자로 바꾼 뒤 ^[a-z0-9_]{4,20}$
    password: NewPassword  # 8~128자, 영문·숫자·특수문자 각 1자 이상
    name: Name
    nick_name: NickName = None  # 빈 문자열이면 None
    phone: Phone  # 010-1234-5678 모양으로 저장
    # POST /verification/phone/verify로 받은 증표 (purpose SIGNUP_PHONE, 위 phone과 같은 번호). 가입할 때 1회 사용된다
    phone_verification_token: str = Field(min_length=1, max_length=2048, repr=False)

    @model_validator(mode="after")
    def _password_not_login_id(self):
        if self.password.lower() == self.login_id:
            raise ValueError("비밀번호는 아이디와 같을 수 없습니다.")
        return self


class UserLogin(BaseModel):
    # 형식 검사는 하지 않는다: 아이디 규칙을 흘리지 않고 예전 규칙으로 만든 계정도 막지 않기 위해 (틀리면 401)
    login_id: Annotated[Annotated[str, Field(min_length=1, max_length=50)], BeforeValidator(normalize_login_id)]
    password: str = Field(min_length=1, max_length=128, repr=False)  # 강도 규칙 없음 (기존 계정도 로그인)


class UserUpdate(BaseModel):
    """PATCH /users/me: 보낸 필드만 바꾼다. nick_name에 null을 보내면 닉네임을 지운다."""

    model_config = ConfigDict(extra="forbid")  # login_id·password처럼 바꿀 수 없는 필드는 422로 알려 준다

    name: Name | None = None
    nick_name: NickName = None
    phone: Phone | None = None
    # phone을 바꿀 때만 필요하다 (purpose CHANGE_PHONE, 새 번호와 같은 번호). 다른 필드만 바꿀 때는 보내지 않는다
    phone_verification_token: str | None = Field(default=None, min_length=1, max_length=2048, repr=False)

    @model_validator(mode="after")
    def _required_fields_not_null(self):
        labels = {"name": "이름은", "phone": "휴대폰 번호는"}  # 가입 때 필수였던 값은 비울 수 없다
        for field, label in labels.items():
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{label} 비울 수 없습니다.")
        return self


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128, repr=False)  # 강도 규칙 없음
    new_password: ChangedPassword


class UserResponse(BaseModel):
    user_id: int
    login_id: str
    name: str
    nick_name: str | None
    phone: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    """갱신·비밀번호 변경 응답. 액세스 토큰은 본문, 갱신 토큰은 본문에 없다 — httpOnly 쿠키(refresh_token)로만 내려간다."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int  # 액세스 토큰 수명(초). 프론트는 이보다 조금 일찍 갱신하면 된다
    session_expires_at: datetime  # 갱신 토큰 만료 시각(UTC). 이때까지 갱신하지 않으면 다시 로그인


class LoginOk(TokenResponse):
    """로그인 성공(등록 기기이거나 새 기기 인증을 마침). status로 아래 DeviceChallenge와 구분한다."""

    status: Literal["OK"] = "OK"


class DeviceChallenge(BaseModel):
    """새 기기에서 비밀번호는 맞았지만 세션은 주지 않았다. 휴대폰 인증(login/device/send → verification/phone/verify)을 마치고
    POST /users/login/device로 challenge_token과 인증 증표를 보내야 로그인된다."""

    status: Literal["DEVICE_VERIFICATION_REQUIRED"] = "DEVICE_VERIFICATION_REQUIRED"
    challenge_token: str = Field(repr=False)
    phone_masked: str  # 010-****-5678


class DeviceChallengeSend(BaseModel):
    challenge_token: str = Field(min_length=1, max_length=2048, repr=False)


class DeviceLogin(DeviceChallengeSend):
    # POST /users/login/device/send로 받은 인증번호를 POST /verification/phone/verify로 확인해 받은 증표 (purpose NEW_DEVICE)
    phone_verification_token: str = Field(min_length=1, max_length=2048, repr=False)


class DeviceResponse(BaseModel):
    device_id: int
    label: str
    created_at: datetime
    last_used_at: datetime
    current: bool  # 이 요청의 기기 쿠키가 이 기기인가


class WithdrawalBlocker(BaseModel):
    """탈퇴를 막는 사유 하나. 화면은 account_type·account_id·card_id로 해당 계좌·카드 화면 링크를 만든다."""

    code: Literal["ACTIVE_DEPOSIT", "ACTIVE_SAVINGS", "CHECKING_BALANCE", "CARD_UNPAID"]
    message: str
    account_type: Literal["checking", "deposit", "savings"] | None = None
    account_id: int | None = None
    card_id: int | None = None  # CARD_UNPAID: 신용카드


class WithdrawalStatus(BaseModel):
    can_withdraw: bool
    blockers: list[WithdrawalBlocker]


class WithdrawalRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128, repr=False)  # 강도 규칙 없음
    # POST /verification/phone/send-for-me {purpose: "WITHDRAWAL"}(등록 번호) → /verify로 받은 증표
    phone_verification_token: str = Field(min_length=1, max_length=2048, repr=False)
