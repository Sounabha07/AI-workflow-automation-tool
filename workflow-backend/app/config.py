from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # .env is shared with docker compose (e.g. GEMINI_API_KEY for the
        # worker), so keys this class doesn't declare are ignored, not errors.
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str
    redis_url: str = "redis://localhost:6379/0"
    db_pool_min_size: int = 2
    db_pool_max_size: int = 10
    log_level: str = "INFO"
    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
