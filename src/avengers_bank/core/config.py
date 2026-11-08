from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(min_length=1)
    jwt_secret_key: SecretStr = Field(min_length=32)
    # 액세스 토큰(JWT) 수명. 서버에 저장하지 않으므로 로그아웃·비밀번호 변경 후에도 이 시간만큼은 살아 있다.
    # 그래서 짧게 둔다(피해 시간 상한 = 이 값). 대신 만료되면 갱신 토큰으로 다시 받는다.
    access_token_expire_minutes: int = Field(default=5, gt=0)
    # 갱신 토큰(=세션) 수명. 갱신할 때마다 새로 이만큼 연장된다 → "이 시간 동안 아무것도 안 하면 로그아웃"(슬라이딩 세션)
    session_expire_minutes: int = Field(default=30, gt=0)
    db_echo: bool = False
    # 개발용 API(/dev/...)를 켠다. 운영 환경에서는 켜지 않는다.
    enable_dev_endpoints: bool = False
    # 문자 발송기 (domains/verification/sms.py). 지금은 "dev"(서버 로그 + 메모리 문자함)뿐이다.
    # Literal이라 다른 값이면 서버가 시작되지 않는다: 실제 발송기 없이 운영에 나가 인증번호가 아무에게도 안 가는 일을 막는다
    sms_sender: Literal["dev"] = "dev"
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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
