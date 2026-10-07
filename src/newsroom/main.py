import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import newsroom.models  # noqa: F401  (registers every mapper)
from newsroom.analytics.ingest import EventBuffer
from newsroom.analytics.partitions import ensure_partitions
from newsroom.api import health
from newsroom.api.v1 import router as api_v1_router
from newsroom.core.config import Settings, get_settings
from newsroom.core.db import create_analytics_engine, create_engine, create_sessionmaker
from newsroom.core.errors import install_exception_handlers
from newsroom.core.logging import configure_logging
from newsroom.core.middleware import (
    CsrfCookieMiddleware,
    RequestContextMiddleware,
    VisitorCookieMiddleware,
)
from newsroom.web.admin.desk import router as admin_desk_router
from newsroom.web.admin.manage import router as admin_manage_router
from newsroom.web.admin.pages import router as admin_pages_router
from newsroom.web.admin.publishing import router as admin_publishing_router
from newsroom.web.admin.routes import router as admin_web_router
from newsroom.web.media_files import router as media_files_router
from newsroom.web.public.routes import router as public_web_router
from newsroom.web.templating import STATIC_DIR, templates


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        analytics_engine = create_analytics_engine(settings)
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        app.state.analytics_engine = analytics_engine
        analytics_sessions = create_sessionmaker(analytics_engine)
        app.state.analytics_sessionmaker = analytics_sessions
        app.state.analytics_buffer = EventBuffer(
            analytics_sessions,
            flush_seconds=settings.analytics_flush_seconds,
            flush_size=settings.analytics_flush_size,
            rate_limit=settings.analytics_rate_limit_per_minute,
        )
        try:
            async with analytics_sessions() as db:
                await ensure_partitions(db)
                await db.commit()
        except Exception:
            structlog.get_logger("newsroom.analytics").exception("analytics_partitions_failed")
        flush_task: asyncio.Task[None] | None = None
        if settings.analytics_flush_seconds > 0:
            flush_task = asyncio.create_task(_flush_analytics(app.state.analytics_buffer))
        try:
            yield
        finally:
            if flush_task is not None:
                flush_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await flush_task
            await app.state.analytics_buffer.flush()
            await engine.dispose()
            await analytics_engine.dispose()

    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        debug=settings.debug,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.templates = templates

    install_exception_handlers(app)
    app.add_middleware(CsrfCookieMiddleware, settings=settings)
    app.add_middleware(VisitorCookieMiddleware, settings=settings)
    app.add_middleware(RequestContextMiddleware)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(media_files_router)
    app.include_router(health.router)
    app.include_router(api_v1_router)
    app.include_router(admin_web_router)
    app.include_router(admin_desk_router)
    app.include_router(admin_manage_router)
    app.include_router(admin_pages_router)
    app.include_router(admin_publishing_router)
    app.include_router(public_web_router)
    return app


async def _flush_analytics(buffer: EventBuffer) -> None:
    while True:
        await asyncio.sleep(buffer.flush_seconds)
        try:
            await buffer.flush()
        except Exception:
            structlog.get_logger("newsroom.analytics").exception("analytics_flush_failed")
