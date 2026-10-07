from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from newsroom.core.config import Settings
from newsroom.core.site import load_site_context


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        str(settings.database_url),
        echo=settings.database_echo,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
    )


def create_analytics_engine(settings: Settings) -> AsyncEngine:
    """Separate pool for the analytics database. It never shares a transaction with editorial."""
    return create_async_engine(
        str(settings.analytics_database_url),
        echo=settings.database_echo,
        pool_size=settings.analytics_pool_size,
        max_overflow=settings.analytics_max_overflow,
        pool_pre_ping=True,
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request. Services own their transactions and call ``commit``."""
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        try:
            await load_site_context(request, session)
            yield session
        except BaseException:
            await session.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_analytics_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Read session for rollups. Callers do not commit; closing the session ends the transaction."""
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.analytics_sessionmaker
    async with sessionmaker() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise


AnalyticsSession = Annotated[AsyncSession, Depends(get_analytics_db)]
