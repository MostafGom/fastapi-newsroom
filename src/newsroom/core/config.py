from collections.abc import Mapping
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from pydantic import Field, PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class UnsafeSettings(RuntimeError):
    """Not a ValueError: pydantic would wrap that and print every setting, secrets included."""


_PLACEHOLDER_SECRETS = {"", "change-me", "change_me", "changeme", "secret"}
_MIN_SECRET_LENGTH = 32


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

    @model_validator(mode="after")
    def _refuse_unsafe_production(self) -> Self:
        """A production server does not start with development settings."""
        if not self.is_production:
            return self
        problems: list[str] = []
        if self.debug:
            problems.append("DEBUG must be false (it shows tracebacks to visitors)")
        secret = self.secret_key.get_secret_value()
        if secret.strip().lower() in _PLACEHOLDER_SECRETS or len(secret) < _MIN_SECRET_LENGTH:
            problems.append(
                f"SECRET_KEY must be a random value of at least {_MIN_SECRET_LENGTH} characters"
            )
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true (session cookies need HTTPS)")
        if urlsplit(self.public_base_url).scheme != "https":
            problems.append("PUBLIC_BASE_URL must start with https://")
        if problems:
            raise UnsafeSettings(
                "Unsafe settings for ENVIRONMENT=production: " + "; ".join(problems)
            )
        return self


def proxy_warnings(settings: Settings, environ: Mapping[str, str]) -> list[str]:
    """Uvicorn reads FORWARDED_ALLOW_IPS itself; this only says when it looks wrong.

    Without it, every visitor behind a reverse proxy has the proxy's address, so per-address
    limits apply to the whole site. With ``*``, any client can claim any address.
    """
    trusted = environ.get("FORWARDED_ALLOW_IPS", "").strip()
    if trusted == "*":
        return [
            "FORWARDED_ALLOW_IPS=* trusts X-Forwarded-For from every client; list the proxy "
            "addresses instead unless port 8000 is reachable only from the proxy"
        ]
    if settings.is_production and not trusted:
        return [
            "FORWARDED_ALLOW_IPS is not set; behind a reverse proxy every visitor will have "
            "the proxy's address. Set it to the proxy's address or network"
        ]
    return []


@lru_cache
def get_settings() -> Settings:
    return Settings()
