"""Rebuild rollups from one day's events, and read those rollups back for the desk."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.analytics.models import (
    ArticleClickDaily,
    ArticleDeviceDaily,
    ArticleReferrerDaily,
    ArticleStatsDaily,
    ArticleStatsHourly,
    ArticleStatsWindow,
    PageStatsWindow,
    SectionListingWindow,
    SectionStatsWindow,
    SiteStatsWindow,
    TagStatsWindow,
)

_MEASURES = """
    COUNT(*) FILTER (WHERE type = 'page_view') AS views,
    COUNT(DISTINCT visitor_id) FILTER (WHERE type = 'page_view') AS unique_visitors,
    COALESCE(SUM(engaged_ms) FILTER (WHERE type = 'engagement'), 0) AS engaged_ms_sum,
    COUNT(DISTINCT view_id) FILTER (WHERE type = 'engagement' AND engaged_ms > 0) AS engaged_views,
    COUNT(DISTINCT view_id) FILTER (WHERE scroll_pct >= 75) AS scroll_75,
    COUNT(*) FILTER (WHERE type = 'click') AS clicks
"""

_ARTICLE_TABLES = frozenset({"stats_article_hourly", "stats_article_daily"})
_SITE_TABLES = frozenset({"stats_site_hourly", "stats_site_daily"})
_SECTION_TABLES = frozenset({"stats_section_hourly", "stats_section_daily"})


@dataclass(frozen=True, slots=True)
class Measure:
    views: int = 0
    unique_visitors: int = 0
    engaged_ms_sum: int = 0
    engaged_views: int = 0
    scroll_75: int = 0
    clicks: int = 0


@dataclass(frozen=True, slots=True)
class ArticleMeasure:
    localization_id: uuid.UUID
    article_id: uuid.UUID
    section_id: uuid.UUID
    locale: str
    window_days: int
    views: int
    unique_visitors: int
    engaged_ms_sum: int
    engaged_views: int
    scroll_75: int
    clicks: int


@dataclass(frozen=True, slots=True)
class DayMeasure:
    bucket: datetime
    views: int
    unique_visitors: int
    engaged_ms_sum: int
    engaged_views: int
    scroll_75: int
    clicks: int


@dataclass(frozen=True, slots=True)
class ReferrerMeasure:
    referrer_class: str
    views: int


@dataclass(frozen=True, slots=True)
class DeviceMeasure:
    device_class: str
    views: int


@dataclass(frozen=True, slots=True)
class ClickMeasure:
    target: str
    clicks: int


@dataclass(frozen=True, slots=True)
class SurfaceMeasure:
    surface: str
    views: int
    unique_visitors: int


class AnalyticsRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def replace_article_bucket(
        self, table: str, start: datetime, end: datetime, bucket: datetime
    ) -> None:
        _check(table, _ARTICLE_TABLES)
        model = ArticleStatsHourly if table == "stats_article_hourly" else ArticleStatsDaily
        await self.db.execute(delete(model).where(model.bucket == bucket))
        await self.db.execute(
            text(
                f"INSERT INTO {table} ("
                "localization_id, article_id, section_id, locale, bucket, "
                "views, unique_visitors, engaged_ms_sum, engaged_views, scroll_75, clicks) "
                "SELECT localization_id, (array_agg(article_id))[1], (array_agg(section_id))[1], "
                "(array_agg(locale))[1], :bucket, "
                f"{_MEASURES} "
                "FROM events WHERE occurred_at >= :start AND occurred_at < :end "
                "AND localization_id IS NOT NULL AND article_id IS NOT NULL "
                "AND section_id IS NOT NULL AND surface = 'article' "
                "GROUP BY localization_id"
            ),
            {"start": start, "end": end, "bucket": bucket},
        )

    async def replace_site_bucket(
        self, table: str, start: datetime, end: datetime, bucket: datetime
    ) -> None:
        _check(table, _SITE_TABLES)
        await self.db.execute(
            text(f"DELETE FROM {table} WHERE bucket = :bucket"),
            {"bucket": bucket},
        )
        await self.db.execute(
            text(
                f"INSERT INTO {table} ("
                "bucket, surface, views, unique_visitors, engaged_ms_sum, engaged_views, "
                "scroll_75, clicks) "
                "SELECT :bucket, surface, "
                f"{_MEASURES} "
                "FROM events WHERE occurred_at >= :start AND occurred_at < :end "
                "GROUP BY surface"
            ),
            {"start": start, "end": end, "bucket": bucket},
        )

    async def replace_section_bucket(
        self, table: str, start: datetime, end: datetime, bucket: datetime
    ) -> None:
        _check(table, _SECTION_TABLES)
        await self.db.execute(
            text(f"DELETE FROM {table} WHERE bucket = :bucket"),
            {"bucket": bucket},
        )
        await self.db.execute(
            text(
                f"INSERT INTO {table} ("
                "section_id, bucket, views, unique_visitors, engaged_ms_sum, engaged_views, "
                "scroll_75, clicks) "
                "SELECT section_id, :bucket, "
                f"{_MEASURES} "
                "FROM events WHERE occurred_at >= :start AND occurred_at < :end "
                "AND section_id IS NOT NULL AND surface = 'article' "
                "GROUP BY section_id"
            ),
            {"start": start, "end": end, "bucket": bucket},
        )

    async def replace_referrers(self, start: datetime, end: datetime, bucket: datetime) -> None:
        await self.db.execute(
            delete(ArticleReferrerDaily).where(ArticleReferrerDaily.bucket == bucket)
        )
        await self.db.execute(
            text(
                "INSERT INTO stats_article_referrer_daily "
                "(localization_id, bucket, referrer_class, views) "
                "SELECT localization_id, :bucket, referrer_class, COUNT(*) "
                "FROM events WHERE type = 'page_view' AND localization_id IS NOT NULL "
                "AND occurred_at >= :start AND occurred_at < :end "
                "GROUP BY localization_id, referrer_class"
            ),
            {"start": start, "end": end, "bucket": bucket},
        )

    async def replace_devices(self, start: datetime, end: datetime, bucket: datetime) -> None:
        await self.db.execute(delete(ArticleDeviceDaily).where(ArticleDeviceDaily.bucket == bucket))
        await self.db.execute(
            text(
                "INSERT INTO stats_article_device_daily "
                "(localization_id, bucket, device_class, views) "
                "SELECT localization_id, :bucket, device_class, COUNT(*) "
                "FROM events WHERE type = 'page_view' AND localization_id IS NOT NULL "
                "AND surface = 'article' AND occurred_at >= :start AND occurred_at < :end "
                "GROUP BY localization_id, device_class"
            ),
            {"start": start, "end": end, "bucket": bucket},
        )

    async def replace_clicks(self, start: datetime, end: datetime, bucket: datetime) -> None:
        await self.db.execute(delete(ArticleClickDaily).where(ArticleClickDaily.bucket == bucket))
        await self.db.execute(
            text(
                "INSERT INTO stats_article_click_daily "
                "(localization_id, bucket, click_target, clicks) "
                "SELECT localization_id, :bucket, click_target, COUNT(*) "
                "FROM events WHERE type = 'click' AND localization_id IS NOT NULL "
                "AND click_target IS NOT NULL AND click_target <> '' "
                "AND occurred_at >= :start AND occurred_at < :end "
                "GROUP BY localization_id, click_target"
            ),
            {"start": start, "end": end, "bucket": bucket},
        )

    async def replace_windows(self, days: int, start: datetime) -> None:
        await self.db.execute(
            delete(ArticleStatsWindow).where(ArticleStatsWindow.window_days == days)
        )
        await self.db.execute(delete(SiteStatsWindow).where(SiteStatsWindow.window_days == days))
        await self.db.execute(
            delete(SectionStatsWindow).where(SectionStatsWindow.window_days == days)
        )
        await self.db.execute(
            delete(SectionListingWindow).where(SectionListingWindow.window_days == days)
        )
        await self.db.execute(delete(PageStatsWindow).where(PageStatsWindow.window_days == days))
        await self.db.execute(delete(TagStatsWindow).where(TagStatsWindow.window_days == days))
        params = {"days": days, "start": start}
        await self.db.execute(
            text(
                "INSERT INTO stats_article_window ("
                "localization_id, window_days, article_id, section_id, locale, "
                "views, unique_visitors, engaged_ms_sum, engaged_views, scroll_75, clicks) "
                "SELECT localization_id, :days, (array_agg(article_id))[1], "
                "(array_agg(section_id))[1], (array_agg(locale))[1], "
                f"{_MEASURES} "
                "FROM events WHERE occurred_at >= :start "
                "AND localization_id IS NOT NULL AND article_id IS NOT NULL "
                "AND section_id IS NOT NULL AND surface = 'article' "
                "GROUP BY localization_id"
            ),
            params,
        )
        await self.db.execute(
            text(
                "INSERT INTO stats_site_window ("
                "window_days, surface, views, unique_visitors, engaged_ms_sum, engaged_views, "
                "scroll_75, clicks) "
                "SELECT :days, surface, "
                f"{_MEASURES} "
                "FROM events WHERE occurred_at >= :start "
                "GROUP BY surface"
            ),
            params,
        )
        await self.db.execute(
            text(
                "INSERT INTO stats_section_window ("
                "section_id, window_days, views, unique_visitors, engaged_ms_sum, "
                "engaged_views, scroll_75, clicks) "
                "SELECT section_id, :days, "
                f"{_MEASURES} "
                "FROM events WHERE occurred_at >= :start AND section_id IS NOT NULL "
                "AND surface = 'article' "
                "GROUP BY section_id"
            ),
            params,
        )
        await self.db.execute(
            text(
                "INSERT INTO stats_section_listing_window ("
                "section_id, window_days, views, unique_visitors, engaged_ms_sum, "
                "engaged_views, scroll_75, clicks) "
                "SELECT section_id, :days, "
                f"{_MEASURES} "
                "FROM events WHERE occurred_at >= :start AND surface = 'section' "
                "AND section_id IS NOT NULL "
                "GROUP BY section_id"
            ),
            params,
        )
        await self.db.execute(
            text(
                "INSERT INTO stats_page_window ("
                "page_id, window_days, views, unique_visitors, engaged_ms_sum, "
                "engaged_views, scroll_75, clicks) "
                "SELECT page_id, :days, "
                f"{_MEASURES} "
                "FROM events WHERE occurred_at >= :start AND surface = 'page' "
                "AND page_id IS NOT NULL "
                "GROUP BY page_id"
            ),
            params,
        )
        await self.db.execute(
            text(
                "INSERT INTO stats_tag_window ("
                "tag_id, window_days, views, unique_visitors, engaged_ms_sum, "
                "engaged_views, scroll_75, clicks) "
                "SELECT tag_id, :days, "
                f"{_MEASURES} "
                "FROM events WHERE occurred_at >= :start AND surface = 'tag' "
                "AND tag_id IS NOT NULL "
                "GROUP BY tag_id"
            ),
            params,
        )

    async def site_window(self, days: int) -> Measure:
        row = await self.db.get(SiteStatsWindow, (days, "article"))
        return _measure(row) if row is not None else Measure()

    async def site_surfaces(self, days: int) -> list[SurfaceMeasure]:
        rows = (
            await self.db.scalars(
                select(SiteStatsWindow).where(SiteStatsWindow.window_days == days)
            )
        ).all()
        return [
            SurfaceMeasure(
                surface=row.surface, views=row.views, unique_visitors=row.unique_visitors
            )
            for row in rows
            if row.surface != "article"
        ]

    async def section_window(self, days: int, section_ids: frozenset[uuid.UUID]) -> Measure:
        if not section_ids:
            return Measure()
        rows = (
            await self.db.scalars(
                select(SectionStatsWindow).where(
                    SectionStatsWindow.window_days == days,
                    SectionStatsWindow.section_id.in_(section_ids),
                )
            )
        ).all()
        return _sum(rows)

    async def top_articles(
        self, days: int, section_ids: frozenset[uuid.UUID] | None, limit: int
    ) -> list[ArticleMeasure]:
        stmt = select(ArticleStatsWindow).where(
            ArticleStatsWindow.window_days == days,
            ArticleStatsWindow.views > 0,
        )
        if section_ids is not None:
            stmt = stmt.where(ArticleStatsWindow.section_id.in_(section_ids))
        stmt = stmt.order_by(
            ArticleStatsWindow.views.desc(),
            ArticleStatsWindow.localization_id,
        ).limit(limit)
        rows = (await self.db.scalars(stmt)).all()
        return [_article(row) for row in rows]

    async def article_window(self, localization_id: uuid.UUID, days: int) -> Measure:
        row = await self.db.get(ArticleStatsWindow, (localization_id, days))
        return _measure(row) if row is not None else Measure()

    async def article_windows(
        self, localization_ids: list[uuid.UUID], days: int
    ) -> dict[uuid.UUID, Measure]:
        if not localization_ids:
            return {}
        rows = (
            await self.db.scalars(
                select(ArticleStatsWindow).where(
                    ArticleStatsWindow.window_days == days,
                    ArticleStatsWindow.localization_id.in_(localization_ids),
                )
            )
        ).all()
        return {row.localization_id: _measure(row) for row in rows}

    async def section_listing(self, section_id: uuid.UUID, days: int) -> Measure:
        row = await self.db.get(SectionListingWindow, (section_id, days))
        return _measure(row) if row is not None else Measure()

    async def page_window(self, page_id: uuid.UUID, days: int) -> Measure:
        row = await self.db.get(PageStatsWindow, (page_id, days))
        return _measure(row) if row is not None else Measure()

    async def tag_windows(self, tag_ids: list[uuid.UUID], days: int) -> dict[uuid.UUID, Measure]:
        if not tag_ids:
            return {}
        rows = (
            await self.db.scalars(
                select(TagStatsWindow).where(
                    TagStatsWindow.window_days == days,
                    TagStatsWindow.tag_id.in_(tag_ids),
                )
            )
        ).all()
        return {row.tag_id: _measure(row) for row in rows}

    async def article_days(self, localization_id: uuid.UUID, start: datetime) -> list[DayMeasure]:
        rows = (
            await self.db.scalars(
                select(ArticleStatsDaily)
                .where(
                    ArticleStatsDaily.localization_id == localization_id,
                    ArticleStatsDaily.bucket >= start,
                )
                .order_by(ArticleStatsDaily.bucket)
            )
        ).all()
        return [
            DayMeasure(
                bucket=row.bucket,
                views=row.views,
                unique_visitors=row.unique_visitors,
                engaged_ms_sum=row.engaged_ms_sum,
                engaged_views=row.engaged_views,
                scroll_75=row.scroll_75,
                clicks=row.clicks,
            )
            for row in rows
        ]

    async def referrers(self, localization_id: uuid.UUID, start: datetime) -> list[ReferrerMeasure]:
        rows = (
            await self.db.execute(
                select(ArticleReferrerDaily.referrer_class, ArticleReferrerDaily.views).where(
                    ArticleReferrerDaily.localization_id == localization_id,
                    ArticleReferrerDaily.bucket >= start,
                )
            )
        ).all()
        totals: dict[str, int] = {}
        for referrer_class, views in rows:
            totals[referrer_class] = totals.get(referrer_class, 0) + int(views)
        ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
        return [ReferrerMeasure(referrer_class=key, views=views) for key, views in ranked if views]

    async def devices(self, localization_id: uuid.UUID, start: datetime) -> list[DeviceMeasure]:
        rows = (
            await self.db.execute(
                select(ArticleDeviceDaily.device_class, ArticleDeviceDaily.views).where(
                    ArticleDeviceDaily.localization_id == localization_id,
                    ArticleDeviceDaily.bucket >= start,
                )
            )
        ).all()
        totals: dict[str, int] = {}
        for device_class, views in rows:
            totals[device_class] = totals.get(device_class, 0) + int(views)
        ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
        return [DeviceMeasure(device_class=key, views=views) for key, views in ranked if views]

    async def clicks(
        self, localization_id: uuid.UUID, start: datetime, *, limit: int = 8
    ) -> list[ClickMeasure]:
        rows = (
            await self.db.execute(
                select(ArticleClickDaily.click_target, ArticleClickDaily.clicks).where(
                    ArticleClickDaily.localization_id == localization_id,
                    ArticleClickDaily.bucket >= start,
                )
            )
        ).all()
        totals: dict[str, int] = {}
        for target, clicks in rows:
            totals[target] = totals.get(target, 0) + int(clicks)
        ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
        return [ClickMeasure(target=key, clicks=clicks) for key, clicks in ranked[:limit] if clicks]


def _check(table: str, allowed: frozenset[str]) -> None:
    if table not in allowed:
        raise ValueError("unknown rollup table")


def _measure(
    row: SiteStatsWindow
    | ArticleStatsWindow
    | SectionStatsWindow
    | SectionListingWindow
    | PageStatsWindow
    | TagStatsWindow,
) -> Measure:
    return Measure(
        views=row.views,
        unique_visitors=row.unique_visitors,
        engaged_ms_sum=row.engaged_ms_sum,
        engaged_views=row.engaged_views,
        scroll_75=row.scroll_75,
        clicks=row.clicks,
    )


def _article(row: ArticleStatsWindow) -> ArticleMeasure:
    return ArticleMeasure(
        localization_id=row.localization_id,
        article_id=row.article_id,
        section_id=row.section_id,
        locale=row.locale,
        window_days=row.window_days,
        views=row.views,
        unique_visitors=row.unique_visitors,
        engaged_ms_sum=row.engaged_ms_sum,
        engaged_views=row.engaged_views,
        scroll_75=row.scroll_75,
        clicks=row.clicks,
    )


def _sum(rows: Sequence[SectionStatsWindow]) -> Measure:
    return Measure(
        views=sum(row.views for row in rows),
        unique_visitors=sum(row.unique_visitors for row in rows),
        engaged_ms_sum=sum(row.engaged_ms_sum for row in rows),
        engaged_views=sum(row.engaged_views for row in rows),
        scroll_75=sum(row.scroll_75 for row in rows),
        clicks=sum(row.clicks for row in rows),
    )
