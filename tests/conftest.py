import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine

from newsroom.core.config import Settings, get_settings

ROOT = Path(__file__).resolve().parent.parent


def _analytics_test_url(base: Settings) -> str:
    from sqlalchemy.engine.url import make_url

    if base.test_analytics_database_url is not None:
        chosen = str(base.test_analytics_database_url)
    elif base.test_database_url is not None:
        chosen = (
            make_url(str(base.test_database_url))
            .set(database="newsroom_analytics_test")
            .render_as_string(hide_password=False)
        )
    else:
        raise RuntimeError("TEST_DATABASE_URL must be set (see .env.example)")
    if chosen == str(base.analytics_database_url):
        raise RuntimeError("analytics test database must differ from ANALYTICS_DATABASE_URL")
    return chosen


def _configure_test_env() -> Settings:
    base = Settings()
    if base.test_database_url is None:
        raise RuntimeError("TEST_DATABASE_URL must be set (see .env.example)")
    if str(base.test_database_url) == str(base.database_url):
        raise RuntimeError("TEST_DATABASE_URL must differ from DATABASE_URL")
    os.environ.update(
        DATABASE_URL=str(base.test_database_url),
        ANALYTICS_DATABASE_URL=_analytics_test_url(base),
        ANALYTICS_FLUSH_SECONDS="0",
        ENVIRONMENT="test",
        COOKIE_SECURE="false",
        LOG_JSON="false",
        LOG_LEVEL="WARNING",
        MEDIA_DIR=str(ROOT / ".test-media"),
        OPENROUTER_API_KEY="",
    )
    get_settings.cache_clear()
    return get_settings()


SETTINGS = _configure_test_env()

from newsroom.core.db import get_db  # noqa: E402
from newsroom.main import create_app  # noqa: E402
from newsroom.users.service import UserService  # noqa: E402

STAFF_PASSWORD = "correct-horse-battery"


def _run_migrations(connection: object) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")


def _run_analytics_migrations(connection: object) -> None:
    config = Config(str(ROOT / "alembic_analytics.ini"))
    config.attributes["connection"] = connection
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")


async def _ensure_database(url: str) -> None:
    parsed = make_url(url)
    name = parsed.database or ""
    owner = parsed.username or ""
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
        raise RuntimeError("refusing to create this database name")
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", owner) is None:
        raise RuntimeError("refusing to create a database for this role")
    conn = await asyncpg.connect(
        user=owner,
        password=parsed.password,
        host=parsed.host or "localhost",
        port=parsed.port or 5432,
        database="postgres",
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{name}" OWNER "{owner}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def settings() -> Settings:
    return SETTINGS


@pytest.fixture(scope="session")
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(str(settings.database_url))
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    async with engine.begin() as conn:
        await conn.run_sync(_run_migrations)

    from newsroom.authz.seed import seed_rbac
    from newsroom.locales.seed import seed_locales

    async with AsyncSession(engine) as db:
        await seed_locales(db)
        await seed_rbac(db)
    yield engine
    await engine.dispose()


@pytest.fixture
async def connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with engine.connect() as conn:
        transaction = await conn.begin()
        yield conn
        await transaction.rollback()


@pytest.fixture
async def db(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """Session whose commits become savepoints; everything rolls back after the test."""
    session = AsyncSession(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    yield session
    await session.close()


@pytest.fixture(scope="session")
async def analytics_engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    await _ensure_database(str(settings.analytics_database_url))
    engine = create_async_engine(str(settings.analytics_database_url))
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    async with engine.begin() as conn:
        await conn.run_sync(_run_analytics_migrations)
    from newsroom.analytics.partitions import ensure_partitions

    async with AsyncSession(engine) as db:
        await ensure_partitions(db)
        await db.commit()
    yield engine
    await engine.dispose()


@pytest.fixture
async def client(
    db: AsyncSession, settings: Settings, analytics_engine: AsyncEngine
) -> AsyncIterator[AsyncClient]:
    from newsroom.analytics.ingest import EventBuffer
    from newsroom.core.db import create_sessionmaker

    app = create_app(settings)
    app.state.analytics_engine = analytics_engine
    app.state.analytics_sessionmaker = create_sessionmaker(analytics_engine)
    app.state.analytics_buffer = EventBuffer(
        app.state.analytics_sessionmaker,
        flush_seconds=settings.analytics_flush_seconds,
        flush_size=settings.analytics_flush_size,
        rate_limit=settings.analytics_rate_limit_per_minute,
    )

    async def override_db(request: Request) -> AsyncIterator[AsyncSession]:
        from newsroom.core.site import load_site_context

        await load_site_context(request, db)
        yield db

    app.dependency_overrides[get_db] = override_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@dataclass
class StaffAccount:
    id: object
    email: str
    password: str


MakeStaff = Callable[..., Awaitable[StaffAccount]]


@pytest.fixture
def make_staff(db: AsyncSession) -> MakeStaff:
    counter = 0

    async def factory(role_key: str | None = None, section_id: object = None) -> StaffAccount:
        nonlocal counter
        counter += 1
        email = f"{role_key or 'norole'}{counter}@example.com"
        user = await UserService(db).create_staff(
            email=email,
            display_name=f"Test {role_key}",
            password=STAFF_PASSWORD,
            role_key=role_key,
            section_id=section_id,  # type: ignore[arg-type]
        )
        return StaffAccount(id=user.id, email=email, password=STAFF_PASSWORD)

    return factory


async def api_login(client: AsyncClient, account: StaffAccount, audience: str = "staff") -> str:
    """Log in through the API and return the CSRF token for subsequent unsafe requests."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": account.email, "password": account.password, "audience": audience},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]
