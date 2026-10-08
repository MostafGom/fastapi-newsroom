"""Demo traffic for the analytics database.

Re-running this replaces every row in that database. It does not copy comments
or bookmarks; those stay on the editorial stories the desk already joins in.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from newsroom.analytics.desk import format_duration, scroll_share
from newsroom.analytics.jobs import WINDOWS, window_start
from newsroom.analytics.models import AnalyticsEvent, truncate_statement
from newsroom.analytics.partitions import ensure_partitions
from newsroom.analytics.repository import AnalyticsRepository
from newsroom.articles.models import ArticleLocalization
from newsroom.articles.workflow import ArticleStatus
from newsroom.pages.models import Page
from newsroom.taxonomy.models import Section, Tag

_VISITOR = uuid.UUID("c0ffee00-0000-4000-8000-000000000001")
QUIET_AGE = 14
_OTHER_AGE = 20
_ENGAGED_MS = 15_000
_SCROLL = 80

# Published demo editions. A slug that is not in the database is skipped.
_FEATURED = ("cabinet-budget", "final-whistle", "transfer-window")
_OTHER = (
    "muwazana-2027",
    "editor-politics-note",
    "editor-sports-note",
    "editor-economy-note",
    "editor-science-note",
    "editor-culture-note",
    "writer-economy-note",
    "writer-science-note",
    "writer-culture-note",
)
HOME_TODAY = 2
SECTION_TODAY = 1
PAGE_TODAY = 1
TAG_TODAY = 1
SEARCH_TODAY = 1
# Comments and saves the desk reads from the editorial demo, not from events.
CABINET_COMMENTS = 1
TRANSFER_BOOKMARKS = 1


@dataclass(frozen=True, slots=True)
class _Hit:
    age: int
    referrer: str
    engaged_ms: int = 0
    scroll_pct: int = 0
    click: bool = False
    device: str = "desktop"


def _cabinet() -> tuple[_Hit, ...]:
    today = (
        _Hit(0, "direct", engaged_ms=_ENGAGED_MS, scroll_pct=_SCROLL, click=True),
        _Hit(0, "direct", engaged_ms=_ENGAGED_MS, scroll_pct=_SCROLL),
        _Hit(0, "search"),
        _Hit(0, "social", device="mobile"),
    )
    rest = tuple(_Hit(age, "direct") for age in range(1, 28) if age != QUIET_AGE)
    return today + rest


CABINET = _cabinet()
WHISTLE = tuple(_Hit(age, "direct") for age in range(7))
TRANSFER = (_Hit(0, "direct"),)
_SCRIPTS = {"cabinet-budget": CABINET, "final-whistle": WHISTLE, "transfer-window": TRANSFER}


def _window(hits: tuple[_Hit, ...], days: int) -> tuple[_Hit, ...]:
    return tuple(hit for hit in hits if hit.age < days)


def _views(hits: tuple[_Hit, ...], days: int) -> int:
    return len(_window(hits, days))


def _average(hits: tuple[_Hit, ...], days: int) -> str:
    chosen = _window(hits, days)
    if not chosen:
        return "0:00"
    return format_duration(sum(hit.engaged_ms for hit in chosen) // len(chosen))


def _share(hits: tuple[_Hit, ...], days: int) -> int:
    chosen = _window(hits, days)
    reached = sum(1 for hit in chosen if hit.scroll_pct >= 75)
    return scroll_share(reached, len(chosen))


def _referrers(hits: tuple[_Hit, ...]) -> tuple[tuple[str, int], ...]:
    totals: dict[str, int] = {}
    for hit in hits:
        totals[hit.referrer] = totals.get(hit.referrer, 0) + 1
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    return tuple(ranked)


def _devices(hits: tuple[_Hit, ...], days: int) -> tuple[tuple[str, int], ...]:
    totals: dict[str, int] = {}
    for hit in _window(hits, days):
        totals[hit.device] = totals.get(hit.device, 0) + 1
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    return tuple(ranked)


CABINET_VIEWS_TODAY = _views(CABINET, 1)
CABINET_VIEWS_7 = _views(CABINET, 7)
CABINET_VIEWS_28 = _views(CABINET, 28)
CABINET_TIME_7 = _average(CABINET, 7)
CABINET_SCROLL_7 = _share(CABINET, 7)
CABINET_CLICKS_7 = sum(1 for hit in _window(CABINET, 7) if hit.click)
CABINET_REFERRERS = _referrers(CABINET)
CABINET_DEVICES_7 = _devices(CABINET, 7)
CABINET_CLICK_TARGET = "example.com/budget"
SITE_VIEWS_TODAY = CABINET_VIEWS_TODAY + _views(WHISTLE, 1) + _views(TRANSFER, 1)
SITE_VIEWS_7 = _views(CABINET, 7) + _views(WHISTLE, 7) + _views(TRANSFER, 7)

_CLEAR = text(truncate_statement())


@dataclass(frozen=True, slots=True)
class _Story:
    slug: str
    localization_id: uuid.UUID
    article_id: uuid.UUID
    section_id: uuid.UUID
    locale: str


async def seed_analytics(editorial: AsyncSession, analytics: AsyncSession) -> list[str]:
    """Replace analytics rows with 28 days of traffic for the published demo stories."""
    stories = await _stories(editorial)
    notes = [f"skipped {slug}" for slug in _FEATURED if slug not in stories]
    politics_id = await editorial.scalar(select(Section.id).where(Section.key == "politics"))
    about_id = await editorial.scalar(select(Page.id).where(Page.key == "about"))
    budget_id = await editorial.scalar(select(Tag.id).where(Tag.key == "budget"))
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = _rows(
        stories,
        today,
        politics_id=politics_id,
        about_id=about_id,
        budget_id=budget_id,
    )
    await analytics.execute(_CLEAR)
    await ensure_partitions(analytics, today=today.date(), behind=28)
    if rows:
        await analytics.execute(insert(AnalyticsEvent).values(rows))
    await _roll(analytics, today)
    await analytics.commit()
    notes.append(f"analytics events: {len(rows)}")
    return notes


def _rows(
    stories: dict[str, _Story],
    today: datetime,
    *,
    politics_id: uuid.UUID | None,
    about_id: uuid.UUID | None,
    budget_id: uuid.UUID | None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for slug, hits in _SCRIPTS.items():
        story = stories.get(slug)
        if story is None:
            continue
        for index, hit in enumerate(hits):
            rows.extend(_article(story, hit, index, today))
    for slug, story in stories.items():
        if slug in _SCRIPTS:
            continue
        rows.extend(_article(story, _Hit(_OTHER_AGE, "direct"), 0, today))
    rows.extend(_plain("home", HOME_TODAY, today, surface="home"))
    if politics_id is not None:
        rows.extend(
            _plain("section", SECTION_TODAY, today, surface="section", section_id=politics_id)
        )
    if about_id is not None:
        rows.extend(_plain("page", PAGE_TODAY, today, surface="page", page_id=about_id))
    if budget_id is not None:
        rows.extend(_plain("tag", TAG_TODAY, today, surface="tag", tag_id=budget_id))
    rows.extend(_plain("search", SEARCH_TODAY, today, surface="search"))
    return rows


def _article(story: _Story, hit: _Hit, index: int, today: datetime) -> list[dict[str, object]]:
    when = today - timedelta(days=hit.age) + timedelta(hours=12)
    view_id = uuid.uuid5(_VISITOR, f"view:{story.slug}:{hit.age}:{index}")
    base = {
        "localization_id": story.localization_id,
        "article_id": story.article_id,
        "section_id": story.section_id,
        "page_id": None,
        "tag_id": None,
        "locale": story.locale,
        "surface": "article",
        "visitor_id": uuid.uuid5(_VISITOR, f"{story.slug}:{hit.age}:{index}"),
        "referrer_class": hit.referrer,
        "device_class": hit.device,
        "view_id": view_id,
    }
    rows = [_event(when, "page_view", engaged_ms=0, scroll_pct=0, click_target=None, **base)]
    if hit.engaged_ms or hit.scroll_pct:
        rows.append(
            _event(
                when + timedelta(minutes=1),
                "engagement",
                engaged_ms=hit.engaged_ms,
                scroll_pct=hit.scroll_pct,
                click_target=None,
                **base,
            )
        )
    if hit.click:
        rows.append(
            _event(
                when + timedelta(minutes=2),
                "click",
                engaged_ms=0,
                scroll_pct=0,
                click_target=CABINET_CLICK_TARGET,
                **base,
            )
        )
    return rows


def _plain(
    name: str,
    count: int,
    today: datetime,
    *,
    surface: str,
    section_id: uuid.UUID | None = None,
    page_id: uuid.UUID | None = None,
    tag_id: uuid.UUID | None = None,
) -> list[dict[str, object]]:
    when = today + timedelta(hours=12)
    rows: list[dict[str, object]] = []
    for index in range(count):
        rows.append(
            _event(
                when,
                "page_view",
                localization_id=None,
                article_id=None,
                section_id=section_id,
                page_id=page_id,
                tag_id=tag_id,
                locale="en",
                surface=surface,
                visitor_id=uuid.uuid5(_VISITOR, f"{name}:{index}"),
                referrer_class="direct",
                device_class="desktop",
                view_id=uuid.uuid5(_VISITOR, f"view:{name}:{index}"),
                engaged_ms=0,
                scroll_pct=0,
                click_target=None,
            )
        )
    return rows


def _event(when: datetime, event_type: str, **fields: object) -> dict[str, object]:
    return {"id": uuid.uuid7(), "occurred_at": when, "type": event_type, **fields}


async def _stories(editorial: AsyncSession) -> dict[str, _Story]:
    rows = (
        await editorial.scalars(
            select(ArticleLocalization)
            .where(
                ArticleLocalization.slug.in_(_FEATURED + _OTHER),
                ArticleLocalization.status == ArticleStatus.PUBLISHED,
            )
            .options(selectinload(ArticleLocalization.article))
        )
    ).all()
    return {
        row.slug: _Story(
            slug=row.slug,
            localization_id=row.id,
            article_id=row.article_id,
            section_id=row.article.section_id,
            locale=row.locale,
        )
        for row in rows
    }


async def _roll(analytics: AsyncSession, today: datetime) -> None:
    repo = AnalyticsRepository(analytics)
    for age in range(28):
        start = today - timedelta(days=age)
        end = start + timedelta(days=1)
        await repo.replace_article_bucket("stats_article_daily", start, end, start)
        await repo.replace_site_bucket("stats_site_daily", start, end, start)
        await repo.replace_section_bucket("stats_section_daily", start, end, start)
        await repo.replace_referrers(start, end, start)
        await repo.replace_devices(start, end, start)
        await repo.replace_clicks(start, end, start)
    for days in WINDOWS:
        await repo.replace_windows(days, window_start(days, today))
