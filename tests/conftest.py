import os
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine

from newsroom.core.config import Settings, get_settings


def _configure_test_env() -> Settings:
    base = Settings()
    if base.test_database_url is None:
        raise RuntimeError("TEST_DATABASE_URL must be set (see .env.example)")
    if str(base.test_database_url) == str(base.database_url):
        raise RuntimeError("TEST_DATABASE_URL must differ from DATABASE_URL")
    os.environ.update(
        DATABASE_URL=str(base.test_database_url),
        ENVIRONMENT="test",
        COOKIE_SECURE="false",
        LOG_JSON="false",
        LOG_LEVEL="WARNING",
    )
    get_settings.cache_clear()
    return get_settings()


SETTINGS = _configure_test_env()

from newsroom.core.db import get_db  # noqa: E402
from newsroom.main import create_app  # noqa: E402
from newsroom.users.service import UserService  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STAFF_PASSWORD = "correct-horse-battery"


def _run_migrations(connection: object) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")


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


@pytest.fixture
async def client(db: AsyncSession, settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)

    async def override_db() -> AsyncIterator[AsyncSession]:
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
