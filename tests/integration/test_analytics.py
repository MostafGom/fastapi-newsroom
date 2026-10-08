import re
import uuid
from typing import cast

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import selectinload

from newsroom.analytics.jobs import refresh_analytics
from newsroom.analytics.models import AnalyticsEvent, truncate_statement
from newsroom.analytics.tokens import PageClaims, issue_page_token
from newsroom.articles.models import ArticleLocalization
from newsroom.core.config import Settings
from newsroom.pages.models import Page
from newsroom.seed.analytics import (
    CABINET_CLICK_TARGET,
    CABINET_CLICKS_7,
    CABINET_COMMENTS,
    CABINET_DEVICES_7,
    CABINET_REFERRERS,
    CABINET_SCROLL_7,
    CABINET_TIME_7,
    CABINET_VIEWS_7,
    CABINET_VIEWS_TODAY,
    HOME_TODAY,
    PAGE_TODAY,
    SEARCH_TODAY,
    SECTION_TODAY,
    SITE_VIEWS_7,
    SITE_VIEWS_TODAY,
    TAG_TODAY,
    TRANSFER_BOOKMARKS,
    seed_analytics,
)
from newsroom.seed.demo import seed_demo
from newsroom.taxonomy.models import Section
from tests.conftest import MakeStaff, StaffAccount

CSRF_FIELD = re.compile(r'name="csrf_token" value="([^"]+)"')


async def _truncate(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(truncate_statement()))


async def _login(client: AsyncClient, account: StaffAccount) -> None:
    client.cookies.clear()
    form = await client.get("/admin/login")
    response = await client.post(
        "/admin/login",
        data={"csrf_token": _csrf(form.text), "email": account.email, "password": account.password},
    )
    assert response.status_code == 303
    client.cookies.set("nr_ui_locale", "en")


def _csrf(html: str) -> str:
    match = CSRF_FIELD.search(html)
    assert match is not None
    return match.group(1)


async def _localization(db: AsyncSession, slug: str) -> ArticleLocalization:
    row = await db.scalar(
        select(ArticleLocalization)
        .where(ArticleLocalization.slug == slug)
        .options(selectinload(ArticleLocalization.article))
    )
    assert row is not None
    return row


def _token(settings: Settings, row: ArticleLocalization) -> str:
    return issue_page_token(
        settings.secret_key.get_secret_value(),
        PageClaims(
            surface="article",
            locale=row.locale,
            localization_id=row.id,
            article_id=row.article_id,
            section_id=row.article.section_id,
        ),
        ttl_seconds=600,
    )


async def _collect(
    client: AsyncClient,
    token: str,
    *,
    visitor: uuid.UUID,
    view_id: uuid.UUID,
    event_type: str = "page_view",
    engaged_ms: int = 0,
    scroll_pct: int = 0,
    click_target: str | None = None,
    staff: bool = False,
) -> None:
    client.cookies.set("nr_vid", str(visitor))
    if staff:
        client.cookies.set("nr_staff", "present")
    else:
        client.cookies.pop("nr_staff", None)
    response = await client.post(
        "/api/v1/collect",
        json={
            "token": token,
            "type": event_type,
            "view_id": str(view_id),
            "engaged_ms": engaged_ms,
            "scroll_pct": scroll_pct,
            "click_target": click_target,
        },
    )
    assert response.status_code == 204


async def test_beacon_rolls_up_and_the_desk_is_section_scoped(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    analytics_engine: AsyncEngine,
    make_staff: MakeStaff,
) -> None:
    await _truncate(analytics_engine)
    try:
        await seed_demo(db)
        politics = await _localization(db, "cabinet-budget")
        sports = await _localization(db, "final-whistle")
        page = await client.get("/en/article/cabinet-budget")
        assert page.status_code == 200
        assert "data-analytics-token" in page.text
        search = await client.get("/en/search")
        assert search.status_code == 200
        assert "data-analytics-token" in search.text
        tag = await client.get("/en/tag/budget")
        assert tag.status_code == 200
        assert "data-analytics-token" in tag.text

        politics_token = _token(settings, politics)
        sports_token = _token(settings, sports)
        reader_a = uuid.uuid4()
        reader_b = uuid.uuid4()
        view_a = uuid.uuid4()
        await _collect(client, politics_token, visitor=reader_a, view_id=view_a)
        await _collect(client, politics_token, visitor=reader_b, view_id=uuid.uuid4())
        await _collect(
            client,
            politics_token,
            visitor=reader_a,
            view_id=view_a,
            event_type="engagement",
            engaged_ms=15_000,
            scroll_pct=80,
        )
        await _collect(
            client,
            politics_token,
            visitor=reader_a,
            view_id=view_a,
            event_type="click",
            click_target="example.com/budget",
        )
        await _collect(client, sports_token, visitor=uuid.uuid4(), view_id=uuid.uuid4())
        await _collect(
            client, politics_token, visitor=uuid.uuid4(), view_id=uuid.uuid4(), staff=True
        )
        client.cookies.set("nr_vid", str(uuid.uuid4()))
        client.cookies.pop("nr_staff", None)
        ignored = await client.post(
            "/api/v1/collect",
            json={
                "token": "not-a-token",
                "type": "page_view",
                "view_id": str(uuid.uuid4()),
            },
        )
        assert ignored.status_code == 204

        async with AsyncSession(analytics_engine) as analytics:
            stored = await analytics.scalar(select(func.count()).select_from(AnalyticsEvent))
            assert stored == 5
            await analytics.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS events_y2020m01d01 PARTITION OF events "
                    "FOR VALUES FROM ('2020-01-01T00:00:00+00') TO ('2020-01-02T00:00:00+00')"
                )
            )
            await analytics.commit()
            dropped = await refresh_analytics(analytics, retention_days=90)
        assert dropped == 1

        admin = await make_staff("admin")
        await _login(client, admin)
        desk = await client.get("/admin/")
        assert desk.status_code == 200
        assert "Performance" in desk.text
        assert "Cabinet approves the 2027 budget" in desk.text
        assert "Final whistle in the cup tie" in desk.text
        assert desk.text.index("Cabinet approves the 2027 budget") < desk.text.index(
            "Final whistle in the cup tie"
        )
        story = await client.get(f"/admin/stories/{politics.id}/analytics")
        assert story.status_code == 200
        assert "0:07" in story.text
        assert "50%" in story.text
        assert "Direct" in story.text

        await _login(client, await make_staff("editor", section_id=sports.article.section_id))
        sports_desk = await client.get("/admin/")
        assert "Final whistle in the cup tie" in sports_desk.text
        assert "Cabinet approves the 2027 budget" not in sports_desk.text
        hidden = await client.get(f"/admin/stories/{politics.id}/analytics")
        assert hidden.status_code == 403

        await _login(client, await make_staff("editor", section_id=politics.article.section_id))
        politics_desk = await client.get("/admin/")
        assert "Cabinet approves the 2027 budget" in politics_desk.text
        assert "Final whistle in the cup tie" not in politics_desk.text

        await _login(client, await make_staff("writer"))
        writer = await client.get("/admin/")
        assert "Performance" not in writer.text
        denied = await client.get(f"/admin/stories/{politics.id}/analytics")
        assert denied.status_code == 403
        listed = await client.get("/admin/stories")
        assert "Visits" not in listed.text
    finally:
        await _truncate(analytics_engine)


_REFERRER_LABELS = {"direct": "Direct", "search": "Search", "social": "Social"}
_DEVICE_LABELS = {"desktop": "Desktop", "mobile": "Mobile", "tablet": "Tablet", "other": "Other"}


class _AnalyticsDown:
    """Session that fails as soon as the desk tries to read a rollup."""

    async def __aenter__(self) -> _AnalyticsDown:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get(self, *_args: object, **_kwargs: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("analytics down"))


async def _stored(engine: AsyncEngine) -> int:
    async with AsyncSession(engine) as db:
        count = await db.scalar(select(func.count()).select_from(AnalyticsEvent))
    return int(count or 0)


def _claims() -> PageClaims:
    return PageClaims(
        surface="article",
        locale="en",
        localization_id=uuid.uuid4(),
        article_id=uuid.uuid4(),
        section_id=uuid.uuid4(),
    )


async def test_collect_drops_bots_and_incomplete_events(
    client: AsyncClient, settings: Settings, analytics_engine: AsyncEngine
) -> None:
    await _truncate(analytics_engine)
    try:
        secret = settings.secret_key.get_secret_value()
        valid = issue_page_token(secret, _claims(), ttl_seconds=600)
        expired = issue_page_token(secret, _claims(), ttl_seconds=60, now=1)
        client.cookies.clear()
        missing = await client.post(
            "/api/v1/collect",
            json={"token": valid, "type": "page_view", "view_id": str(uuid.uuid4())},
        )
        assert missing.status_code == 204
        client.cookies.set("nr_vid", str(uuid.uuid4()))
        bot = await client.post(
            "/api/v1/collect",
            json={"token": valid, "type": "page_view", "view_id": str(uuid.uuid4())},
            headers={"user-agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"},
        )
        assert bot.status_code == 204
        bare_click = await client.post(
            "/api/v1/collect",
            json={"token": valid, "type": "click", "view_id": str(uuid.uuid4())},
        )
        assert bare_click.status_code == 204
        stale = await client.post(
            "/api/v1/collect",
            json={"token": expired, "type": "page_view", "view_id": str(uuid.uuid4())},
        )
        assert stale.status_code == 204
        assert await _stored(analytics_engine) == 0
    finally:
        await _truncate(analytics_engine)


async def test_seeded_history_fills_the_desk(
    client: AsyncClient,
    db: AsyncSession,
    analytics_engine: AsyncEngine,
    make_staff: MakeStaff,
) -> None:
    await _truncate(analytics_engine)
    try:
        await seed_demo(db)
        async with AsyncSession(analytics_engine) as analytics:
            await seed_analytics(db, analytics)
        politics = await _localization(db, "cabinet-budget")
        sports = await _localization(db, "final-whistle")
        transfer = await _localization(db, "transfer-window")

        await _login(client, await make_staff("admin"))
        desk = await client.get("/admin/")
        assert desk.status_code == 200
        today, rest = desk.text.split("Today", 1)[1].split("7 days", 1)
        week = rest.split("Top stories", 1)[0]
        assert f"<strong>{SITE_VIEWS_TODAY}</strong>" in today
        assert f"<strong>{SITE_VIEWS_7}</strong>" in week
        assert f"<span>Home</span><span>{HOME_TODAY}</span>" in desk.text
        assert f"<span>Section lists</span><span>{SECTION_TODAY}</span>" in desk.text
        assert f"<span>Tags</span><span>{TAG_TODAY}</span>" in desk.text
        assert f"<span>Site pages</span><span>{PAGE_TODAY}</span>" in desk.text
        assert f"<span>Search</span><span>{SEARCH_TODAY}</span>" in desk.text
        assert "Section page" not in desk.text
        assert desk.text.index("Cabinet approves the 2027 budget") < desk.text.index(
            "Final whistle in the cup tie"
        )

        story = await client.get(f"/admin/stories/{politics.id}/analytics")
        assert story.status_code == 200
        today_block = story.text.split("Today", 1)[1].split("7 days", 1)[0]
        assert f"<strong>{CABINET_VIEWS_TODAY}</strong>" in today_block
        assert f"<strong>{CABINET_VIEWS_7}</strong>" in story.text
        assert CABINET_TIME_7 in story.text
        assert f"{CABINET_SCROLL_7}%" in story.text
        assert f"<strong>{CABINET_CLICKS_7}</strong>" in story.text
        assert f"<strong>{CABINET_COMMENTS}</strong><span>Comments</span>" in story.text
        for key, views in CABINET_REFERRERS:
            label = _REFERRER_LABELS[key]
            assert f"<span>{label}</span><span>{views}</span>" in story.text
        for key, views in CABINET_DEVICES_7:
            label = _DEVICE_LABELS[key]
            assert f"<span>{label}</span><span>{views}</span>" in story.text
        assert f'<span dir="ltr">{CABINET_CLICK_TARGET}</span><span>{CABINET_CLICKS_7}</span>' in (
            story.text
        )
        details = story.text.split("<details", 1)[1]
        assert details.count("<li>") == 28
        assert details.count("<span>0 Visits") == 1

        saved = await client.get(f"/admin/stories/{transfer.id}/analytics")
        assert f"<strong>{TRANSFER_BOOKMARKS}</strong><span>Saves</span>" in saved.text

        listed = await client.get("/admin/stories", params={"q": "Cabinet"})
        assert f"{CABINET_VIEWS_7} Visits" in listed.text
        politics_section = await db.scalar(select(Section.id).where(Section.key == "politics"))
        about = await db.scalar(select(Page.id).where(Page.key == "about"))
        assert politics_section is not None
        assert about is not None
        section = await client.get(f"/admin/sections/{politics_section}/analytics")
        assert section.status_code == 200
        assert f"<strong>{SECTION_TODAY}</strong>" in section.text
        site_page = await client.get(f"/admin/pages/{about}/analytics")
        assert site_page.status_code == 200
        assert f"<strong>{PAGE_TODAY}</strong>" in site_page.text
        tags = await client.get("/admin/tags")
        assert f"{TAG_TODAY} Visits · 7 days" in tags.text

        await _login(client, await make_staff("editor", section_id=sports.article.section_id))
        sports_desk = await client.get("/admin/")
        assert "Final whistle in the cup tie" in sports_desk.text
        assert "Cabinet approves the 2027 budget" not in sports_desk.text
        assert "Section page" in sports_desk.text
        assert "Sports" in sports_desk.text
        assert "Other pages" not in sports_desk.text
        hidden_section = await client.get(f"/admin/sections/{politics_section}/analytics")
        assert hidden_section.status_code == 403
    finally:
        await _truncate(analytics_engine)


async def test_dashboard_stays_up_when_analytics_is_down(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    await seed_demo(db)
    politics = await _localization(db, "cabinet-budget")
    app = cast(FastAPI, cast(ASGITransport, client._transport).app)
    app.state.analytics_sessionmaker = lambda: _AnalyticsDown()
    await _login(client, await make_staff("admin"))
    desk = await client.get("/admin/")
    assert desk.status_code == 200
    assert "Traffic numbers are unavailable right now." in desk.text
    story = await client.get(f"/admin/stories/{politics.id}/analytics")
    assert story.status_code == 200
    assert "Traffic numbers are unavailable right now." in story.text
