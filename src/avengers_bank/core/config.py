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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
