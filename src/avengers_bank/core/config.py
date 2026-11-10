import re
from datetime import datetime
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(min_length=1)
    jwt_secret_key: SecretStr = Field(min_length=32)
    # 액세스 토큰(JWT) 수명. 서버에 저장하지 않으므로 로그아웃·비밀번호 변경 후에도 이 시간만큼은 살아 있다.
    # 그래서 짧게 둔다(피해 시간 상한 = 이 값). 대신 만료되면 갱신 토큰으로 다시 받는다.
    access_token_expire_minutes: int = Field(default=5, gt=0)
    # 갱신 토큰(=세션) 수명. 갱신할 때마다 새로 이만큼 연장된다 → "이 시간 동안 아무것도 안 하면 로그아웃"(슬라이딩 세션)
    session_expire_minutes: int = Field(default=30, gt=0)
    # 쿠키(갱신 토큰·기기 토큰)에 Secure를 붙인다. 운영(HTTPS)에서는 반드시 True. http://로 여는 개발·테스트에서만 끈다
    cookie_secure: bool = True
    # 두 쿠키가 브라우저에서 이 경로 아래로만 간다. 브라우저는 Next.js 프록시(/api/...)로 API를 부르므로 /api/users.
    # 갱신·로그아웃·로그인·기기 API만 쿠키를 받고 나머지 API(계좌·이체 등)에는 아예 실려 가지 않는다
    refresh_cookie_path: str = "/api/users"
    # 기기 등록(B1) 쿠키 수명(일). 이 기간 안에 쓰지 않아도 쿠키가 사라지면 새 기기로 취급된다
    device_cookie_days: int = Field(default=365, gt=0)
    db_echo: bool = False
    # 개발용 API(/dev/...)를 켠다. 운영 환경에서는 켜지 않는다.
    enable_dev_endpoints: bool = False
    # 문자 발송기 (domains/verification/sms.py). 지금은 "dev"(서버 로그 + 메모리 문자함)뿐이다.
    # Literal이라 다른 값이면 서버가 시작되지 않는다: 실제 발송기 없이 운영에 나가 인증번호가 아무에게도 안 가는 일을 막는다
    sms_sender: Literal["dev"] = "dev"
    # 시연용 새 기기 인증: 정확히 한 계정/등록 번호에만 적용하고 종료 시각 뒤에는 자동으로 꺼진다.
    # 코드는 서버 환경변수에만 보관하며 API 응답이나 저장소에 넣지 않는다.
    demo_device_login_id: str | None = None
    demo_device_phone: str | None = None
    demo_device_code: SecretStr | None = None
    demo_device_until: datetime | None = None

    @model_validator(mode="after")
    def validate_demo_device(self):
        values = (self.demo_device_login_id, self.demo_device_phone, self.demo_device_code, self.demo_device_until)
        if any(value is not None for value in values):
            if any(value is None for value in values):
                raise ValueError("시연용 새 기기 인증 설정은 계정·번호·코드·종료 시각을 모두 지정해야 합니다.")
            if not re.fullmatch(r"\d{6}", self.demo_device_code.get_secret_value()):
                raise ValueError("시연용 새 기기 인증 코드는 숫자 6자리여야 합니다.")
            if self.demo_device_until.tzinfo is None or self.demo_device_until.utcoffset() is None:
                raise ValueError("시연용 새 기기 인증 종료 시각에는 시간대를 지정해야 합니다.")
        return self
    # CORS로 허용할 프론트 주소 (쉼표로 구분, C-047)
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    # AI 금융 비서 (C-070). 키가 없으면 /agent/chat은 503을 돌려준다
    gemini_api_key: SecretStr | None = None
    agent_model: str = "gemini-2.5-flash"
    agent_timeout_seconds: float = Field(default=30, gt=0)
    # 약관 검색 (C-075). 문서와 질의는 반드시 같은 모델·차원으로 임베딩한다. 바꾸면 전체 재색인
    terms_root: str = "docs/terms"
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = Field(default=768, gt=0)
    embedding_timeout_seconds: float = Field(default=20, gt=0)
    # 이보다 낮은 벡터 유사도는 근거로 쓰지 않는다. 0.6 = scripts/eval_terms.py 실측(gemini-embedding-001·768, 2026-11-07):
    # 기대 조항 최저 0.622, 근거 없는 질문 최고 0.594. 모델·차원을 바꾸면 다시 잰다
    terms_min_score: float = Field(default=0.6, ge=-1, le=1)

    # ClearingHub 연동 (docs/SPEC.md). 하나라도 비어 있으면 타행 이체 기능이 꺼진다(503 INTERBANK_DISABLED).
    # 개인키·API 키는 .env에만 둔다(커밋 금지). 허브 주소·공개키는 공개 값이다
    hub_url: str = "https://clearing-hub.ai-agent-develop.cloud"
    hub_public_key: str | None = None
    bank_code: str | None = None
    bank_name: str = "SpiderBank"
    bank_api_key: SecretStr | None = None
    bank_private_key: SecretStr | None = None

    @property
    def receiver_enabled(self) -> bool:
        # 받는 쪽(/interbank)은 허브 서명 검증과 응답 서명에 두 키만 쓴다. 등록(ping) 전에도 켜져 있어야 한다
        return bool(self.hub_public_key and self.bank_private_key)

    @property
    def interbank_enabled(self) -> bool:
        return all([self.hub_public_key, self.bank_code, self.bank_api_key, self.bank_private_key])

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
