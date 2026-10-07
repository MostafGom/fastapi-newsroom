from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Newsroom"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False

    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+asyncpg://newsroom:newsroom@localhost:5433/newsroom")
    )
    test_database_url: PostgresDsn | None = None
    analytics_database_url: PostgresDsn = Field(
        default=PostgresDsn(
            "postgresql+asyncpg://newsroom:newsroom@localhost:5433/newsroom_analytics"
        )
    )
    test_analytics_database_url: PostgresDsn | None = None
    database_echo: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 10
    analytics_pool_size: int = 2
    analytics_max_overflow: int = 4
    analytics_flush_seconds: float = 2.0
    analytics_flush_size: int = 200
    analytics_rate_limit_per_minute: int = 60
    analytics_token_ttl_seconds: int = 30 * 60
    analytics_raw_retention_days: int = 90

    secret_key: SecretStr = SecretStr("change-me")

    log_level: str = "INFO"
    log_json: bool = True

    default_locale: str = "ar"
    supported_locales: list[str] = ["ar", "en"]

    cookie_secure: bool = True
    reader_session_cookie: str = "nr_session"
    staff_session_cookie: str = "nr_staff"
    visitor_cookie: str = "nr_vid"
    visitor_cookie_days: int = 400
    csrf_cookie: str = "nr_csrf"
    reader_session_ttl_hours: int = 24 * 30
    staff_session_ttl_hours: int = 12
    session_touch_interval_seconds: int = 60

    worker_poll_seconds: int = 30
    media_dir: Path = Path("data/media")
    public_base_url: str = "http://localhost:8000"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None

    openrouter_api_key: SecretStr | None = None
    openrouter_model: str = "google/gemini-2.5-flash"
    openrouter_timeout_seconds: int = 20

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    return Settings()
