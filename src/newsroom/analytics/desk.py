"""Join rollups with editorial titles, comments, and bookmarks. No cross-database SQL."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.analytics.jobs import window_start
from newsroom.analytics.repository import DayMeasure, Measure
from newsroom.analytics.service import AnalyticsService
from newsroom.articles.models import ArticleLocalization, ArticleRevision, Bookmark
from newsroom.auth.principal import Principal
from newsroom.authz.permissions import Perm
from newsroom.comments.models import Comment


@dataclass(frozen=True, slots=True)
class Headline:
    views: int
    uniques: int
    average_time: str
    scroll_pct: int
    clicks: int


@dataclass(frozen=True, slots=True)
class DayRow:
    bucket: datetime
    views: int
    uniques: int
    average_time: str


@dataclass(frozen=True, slots=True)
class ReferrerRow:
    key: str
    views: int


@dataclass(frozen=True, slots=True)
class TopStory:
    localization_id: uuid.UUID
    title: str
    views: int
    uniques: int
    comments: int


@dataclass(frozen=True, slots=True)
class Overview:
    today: Headline
    week: Headline
    top: list[TopStory]


@dataclass(frozen=True, slots=True)
class StoryReport:
    week: Headline
    month: Headline
    days_7: list[DayRow]
    days_28: list[DayRow]
    referrers: list[ReferrerRow]
    comments: int
    bookmarks: int


class DeskAnalytics:
    def __init__(self, editorial: AsyncSession, analytics: AsyncSession) -> None:
        self.editorial = editorial
        self.analytics = AnalyticsService(analytics)

    async def overview(self, staff: Principal) -> Overview:
        sections = staff.grants.sections_with(Perm.ANALYTICS_READ)
        today = await self.analytics.totals(1, sections)
        week = await self.analytics.totals(7, sections)
        ranked = await self.analytics.top(sections)
        titles = await _titles(self.editorial, [row.localization_id for row in ranked])
        comments = await _comment_counts(
            self.editorial,
            [row.localization_id for row in ranked],
            since=window_start(7, datetime.now(UTC)),
        )
        top = [
            TopStory(
                localization_id=row.localization_id,
                title=titles[row.localization_id],
                views=row.views,
                uniques=row.unique_visitors,
                comments=comments.get(row.localization_id, 0),
            )
            for row in ranked
            if row.localization_id in titles
        ]
        return Overview(today=_headline(today), week=_headline(week), top=top)

    async def story(self, localization_id: uuid.UUID, article_id: uuid.UUID) -> StoryReport:
        week, month, days, referrers = await self.analytics.story(localization_id)
        by_day = {row.bucket.date(): row for row in days}
        return StoryReport(
            week=_headline(week),
            month=_headline(month),
            days_7=_fill(by_day, 7),
            days_28=_fill(by_day, 28),
            referrers=[ReferrerRow(key=row.referrer_class, views=row.views) for row in referrers],
            comments=await _comment_total(self.editorial, localization_id),
            bookmarks=await _bookmark_total(self.editorial, article_id),
        )


def format_duration(ms: int) -> str:
    total = max(ms, 0) // 1000
    minutes, seconds = divmod(total, 60)
    return f"{minutes}:{seconds:02d}"


def scroll_share(reached: int, views: int) -> int:
    if views <= 0:
        return 0
    return round(100 * reached / views)


def _headline(measure: Measure) -> Headline:
    return Headline(
        views=measure.views,
        uniques=measure.unique_visitors,
        average_time=format_duration(
            measure.engaged_ms_sum // measure.views if measure.views else 0
        ),
        scroll_pct=scroll_share(measure.scroll_75, measure.views),
        clicks=measure.clicks,
    )


def _fill(by_day: dict[date, DayMeasure], days: int) -> list[DayRow]:
    today = datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    rows: list[DayRow] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        found = by_day.get(day)
        if found is None:
            rows.append(DayRow(bucket=_midnight(day), views=0, uniques=0, average_time="0:00"))
            continue
        rows.append(
            DayRow(
                bucket=found.bucket,
                views=found.views,
                uniques=found.unique_visitors,
                average_time=format_duration(
                    found.engaged_ms_sum // found.views if found.views else 0
                ),
            )
        )
    return rows


def _midnight(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC)


async def _titles(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(ArticleLocalization.id, ArticleRevision.title)
            .join(ArticleRevision, ArticleRevision.id == ArticleLocalization.current_revision_id)
            .where(ArticleLocalization.id.in_(ids))
        )
    ).all()
    return {localization_id: title for localization_id, title in rows}


async def _comment_counts(
    db: AsyncSession, ids: list[uuid.UUID], *, since: datetime
) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Comment.localization_id, func.count())
            .where(
                Comment.localization_id.in_(ids),
                Comment.hidden_at.is_(None),
                Comment.created_at >= since,
            )
            .group_by(Comment.localization_id)
        )
    ).all()
    return {localization_id: int(count) for localization_id, count in rows}


async def _comment_total(db: AsyncSession, localization_id: uuid.UUID) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(Comment)
        .where(Comment.localization_id == localization_id, Comment.hidden_at.is_(None))
    )
    return int(count or 0)


async def _bookmark_total(db: AsyncSession, article_id: uuid.UUID) -> int:
    count = await db.scalar(
        select(func.count()).select_from(Bookmark).where(Bookmark.article_id == article_id)
    )
    return int(count or 0)
