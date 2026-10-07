"""Read-only measures. Titles and comment counts stay in the editorial database."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.analytics.repository import (
    AnalyticsRepository,
    ArticleMeasure,
    DayMeasure,
    Measure,
    ReferrerMeasure,
)


class AnalyticsService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = AnalyticsRepository(db)

    async def totals(self, days: int, section_ids: frozenset[uuid.UUID] | None) -> Measure:
        if section_ids is None:
            return await self.repo.site_window(days)
        return await self.repo.section_window(days, section_ids)

    async def top(
        self, section_ids: frozenset[uuid.UUID] | None, *, limit: int = 8
    ) -> list[ArticleMeasure]:
        return await self.repo.top_articles(7, section_ids, limit)

    async def story(
        self, localization_id: uuid.UUID
    ) -> tuple[Measure, Measure, list[DayMeasure], list[ReferrerMeasure]]:
        week = await self.repo.article_window(localization_id, 7)
        month = await self.repo.article_window(localization_id, 28)
        days = await self.repo.article_days(localization_id, _since_28())
        referrers = await self.repo.referrers(localization_id, _since_28())
        return week, month, days, referrers


def _since_28() -> datetime:
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=27)
