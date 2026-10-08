"""Read analytics for a desk screen. A failed read leaves the rest of the page up."""

from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.analytics.desk import DeskAnalytics

log = structlog.get_logger("newsroom.analytics")


async def load_desk[T](
    request: Request,
    editorial: AsyncSession,
    reader: Callable[[DeskAnalytics], Awaitable[T]],
) -> T | None:
    maker = getattr(request.app.state, "analytics_sessionmaker", None)
    if maker is None:
        return None
    try:
        async with maker() as analytics:
            return await reader(DeskAnalytics(editorial, analytics))
    except SQLAlchemyError:
        log.exception("analytics_read_failed")
        return None
