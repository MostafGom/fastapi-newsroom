from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import newsroom.models  # noqa: F401  (registers every mapper)
from newsroom.api import health
from newsroom.api.v1 import router as api_v1_router
from newsroom.core.config import Settings, get_settings
from newsroom.core.db import create_engine, create_sessionmaker
from newsroom.core.errors import install_exception_handlers
from newsroom.core.logging import configure_logging
from newsroom.core.middleware import CsrfCookieMiddleware, RequestContextMiddleware
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
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        try:
            yield
        finally:
            await engine.dispose()

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
