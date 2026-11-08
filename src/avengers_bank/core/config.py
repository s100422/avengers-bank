from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = Field(min_length=1)
    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_expire_minutes: int = Field(default=30, gt=0)
    db_echo: bool = False
    # 개발용 API(/dev/...)를 켠다. 운영 환경에서는 켜지 않는다.
    enable_dev_endpoints: bool = False
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
