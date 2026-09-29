from enum import StrEnum
from functools import lru_cache

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
    database_echo: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 10

    secret_key: SecretStr = SecretStr("change-me")

    log_level: str = "INFO"
    log_json: bool = True

    default_locale: str = "ar"
    supported_locales: list[str] = ["ar", "en"]

    cookie_secure: bool = True
    reader_session_cookie: str = "nr_session"
    staff_session_cookie: str = "nr_staff"
    csrf_cookie: str = "nr_csrf"
    reader_session_ttl_hours: int = 24 * 30
    staff_session_ttl_hours: int = 12
    session_touch_interval_seconds: int = 60

    worker_poll_seconds: int = 30

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    return Settings()
