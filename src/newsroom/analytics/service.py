"""Read-only measures. Titles and comment counts stay in the editorial database."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.analytics.models import OTHER_SURFACES
from newsroom.analytics.repository import (
    AnalyticsRepository,
    ArticleMeasure,
    ClickMeasure,
    DayMeasure,
    DeviceMeasure,
    Measure,
    ReferrerMeasure,
    SurfaceMeasure,
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

    async def surfaces(self, days: int) -> list[SurfaceMeasure]:
        found = {row.surface: row for row in await self.repo.site_surfaces(days)}
        return [
            found.get(key, SurfaceMeasure(surface=key, views=0, unique_visitors=0))
            for key in OTHER_SURFACES
        ]

    async def visits(self, localization_ids: list[uuid.UUID]) -> dict[uuid.UUID, Measure]:
        found = await self.repo.article_windows(localization_ids, 7)
        return {item: found.get(item, Measure()) for item in localization_ids}

    async def story(
        self, localization_id: uuid.UUID
    ) -> tuple[
        Measure,
        Measure,
        Measure,
        list[DayMeasure],
        list[ReferrerMeasure],
        list[DeviceMeasure],
        list[ClickMeasure],
    ]:
        today = await self.repo.article_window(localization_id, 1)
        week = await self.repo.article_window(localization_id, 7)
        month = await self.repo.article_window(localization_id, 28)
        days = await self.repo.article_days(localization_id, _since(28))
        referrers = await self.repo.referrers(localization_id, _since(28))
        devices = await self.repo.devices(localization_id, _since(7))
        clicks = await self.repo.clicks(localization_id, _since(7))
        return today, week, month, days, referrers, devices, clicks

    async def listing(self, section_id: uuid.UUID, days: int) -> Measure:
        return await self.repo.section_listing(section_id, days)

    async def page(self, page_id: uuid.UUID, days: int) -> Measure:
        return await self.repo.page_window(page_id, days)

    async def tags(self, tag_ids: list[uuid.UUID]) -> dict[uuid.UUID, Measure]:
        found = await self.repo.tag_windows(tag_ids, 7)
        return {item: found.get(item, Measure()) for item in tag_ids}


def _since(days: int) -> datetime:
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=days - 1)
