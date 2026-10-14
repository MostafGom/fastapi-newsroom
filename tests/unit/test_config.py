import pytest
from pydantic import PostgresDsn, SecretStr

from newsroom.core.config import Environment, Settings, UnsafeSettings, proxy_warnings

SAFE = {
    "debug": False,
    "secret_key": SecretStr("k" * 48),
    "cookie_secure": True,
    "public_base_url": "https://news.example",
}


def test_production_starts_with_safe_settings() -> None:
    assert Settings(environment=Environment.PRODUCTION, **SAFE).is_production


def test_production_refuses_development_settings() -> None:
    with pytest.raises(UnsafeSettings) as refused:
        Settings(
            environment=Environment.PRODUCTION,
            debug=True,
            secret_key=SecretStr("change-me"),
            cookie_secure=False,
            public_base_url="http://news.example",
            database_url=PostgresDsn("postgresql+asyncpg://newsroom:db-password-value@db/newsroom"),
        )
    message = str(refused.value)
    for setting in ("DEBUG", "SECRET_KEY", "COOKIE_SECURE", "PUBLIC_BASE_URL"):
        assert setting in message
    assert "change-me" not in message
    assert "input_value" not in message
    assert "db-password-value" not in message


@pytest.mark.parametrize(
    "unsafe",
    [
        {"debug": True},
        {"secret_key": SecretStr("CHANGE_ME")},
        {"secret_key": SecretStr("short-but-not-placeholder")},
        {"cookie_secure": False},
        {"public_base_url": "http://news.example"},
    ],
)
def test_each_unsafe_production_setting_is_refused(unsafe: dict) -> None:
    with pytest.raises(UnsafeSettings):
        Settings(environment=Environment.PRODUCTION, **{**SAFE, **unsafe})


def test_development_keeps_its_conveniences() -> None:
    settings = Settings(
        environment=Environment.DEVELOPMENT,
        debug=True,
        secret_key=SecretStr("change-me"),
        cookie_secure=False,
        public_base_url="http://localhost:8000",
    )
    assert settings.debug


def test_production_warns_when_the_proxy_is_not_trusted() -> None:
    production = Settings(environment=Environment.PRODUCTION, **SAFE)
    assert proxy_warnings(production, {}) != []
    assert proxy_warnings(production, {"FORWARDED_ALLOW_IPS": "172.18.0.0/16"}) == []
    assert proxy_warnings(production, {"FORWARDED_ALLOW_IPS": "*"}) != []


def test_development_does_not_need_a_proxy() -> None:
    assert proxy_warnings(Settings(environment=Environment.DEVELOPMENT), {}) == []
