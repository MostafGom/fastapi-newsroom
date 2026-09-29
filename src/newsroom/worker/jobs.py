from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import CursorResult, delete
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.articles.service import ArticleService
from newsroom.auth.models import AuthSession

Job = Callable[[AsyncSession], Awaitable[int]]

SESSION_RETENTION = timedelta(days=30)


async def prune_sessions(db: AsyncSession) -> int:
    """Delete sessions that expired or were revoked more than the retention window ago."""
    cutoff = datetime.now(UTC) - SESSION_RETENTION
    result: CursorResult[Any] = await db.execute(  # type: ignore[assignment]
        delete(AuthSession).where(
            (AuthSession.expires_at < cutoff) | (AuthSession.revoked_at < cutoff)
        )
    )
    await db.commit()
    return result.rowcount or 0


async def publish_scheduled(db: AsyncSession) -> int:
    published = await ArticleService(db).publish_due()
    expired = await ArticleService(db).unpublish_due()
    return published + expired


JOBS: dict[str, Job] = {
    "publish_scheduled": publish_scheduled,
    "prune_sessions": prune_sessions,
}
