from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.articles.models import ArticleLocalization
from newsroom.articles.service import author_for_user
from newsroom.audit.models import AuditEvent
from newsroom.taxonomy.schemas import SectionCreate, SectionTranslationIn
from newsroom.taxonomy.service import TaxonomyService
from newsroom.worker.jobs import publish_scheduled
from tests.conftest import MakeStaff, api_login


def _doc(text: str) -> dict:
    paragraph = {"type": "paragraph", "content": [{"type": "text", "text": text}]}
    return {"type": "doc", "content": [paragraph]}


async def _file(
    client: AsyncClient,
    csrf: str,
    section_id: str,
    author_id: str,
    slug: str,
    title: str,
) -> str:
    created = await client.post(
        "/api/v1/admin/articles",
        headers={"x-csrf-token": csrf},
        json={
            "section_id": section_id,
            "author_ids": [author_id],
            "locale": "en",
            "slug": slug,
            "content": {"title": title, "body": _doc(title)},
        },
    )
    assert created.status_code == 201, created.text
    localization_id = created.json()["localizations"][0]["id"]
    submitted = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/transitions",
        headers={"x-csrf-token": csrf},
        json={"action": "submit", "lock_version": 1},
    )
    assert submitted.status_code == 200, submitted.text
    return localization_id


async def _schedule(
    client: AsyncClient, csrf: str, localization_id: str, publish_at: datetime
) -> None:
    current = await client.get(f"/api/v1/admin/localizations/{localization_id}")
    assert current.status_code == 200, current.text
    approved = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/transitions",
        headers={"x-csrf-token": csrf},
        json={
            "action": "approve",
            "lock_version": current.json()["lock_version"],
            "reason": "embargo, copy already done",
        },
    )
    assert approved.status_code == 200, approved.text
    scheduled = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/transitions",
        headers={"x-csrf-token": csrf},
        json={
            "action": "schedule",
            "lock_version": approved.json()["lock_version"],
            "publish_at": publish_at.isoformat(),
        },
    )
    assert scheduled.status_code == 200, scheduled.text
    assert scheduled.json()["status"] == "scheduled"


async def _row(db: AsyncSession, localization_id: str) -> ArticleLocalization:
    row = await db.get(ArticleLocalization, localization_id)
    assert row is not None
    return row


async def test_due_story_goes_live_and_an_expired_one_comes_down(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    section = await TaxonomyService(db).create_section(
        SectionCreate(
            key="embargo-desk",
            translations=[SectionTranslationIn(locale="en", name="Desk", slug="embargo-desk")],
        )
    )
    writer = await make_staff("writer")
    editor = await make_staff("editor", section_id=section.id)
    author = await author_for_user(db, writer.id)  # type: ignore[arg-type]
    assert author is not None
    section_id = str(section.id)
    author_id = str(author.id)
    writer_csrf = await api_login(client, writer)
    due_id = await _file(client, writer_csrf, section_id, author_id, "due-briefing", "Due briefing")
    held_id = await _file(
        client, writer_csrf, section_id, author_id, "held-briefing", "Held briefing"
    )
    waiting_id = await _file(
        client, writer_csrf, section_id, author_id, "waiting-briefing", "Waiting briefing"
    )

    client.cookies.clear()
    editor_csrf = await api_login(client, editor)
    soon = datetime.now(UTC) + timedelta(hours=2)
    await _schedule(client, editor_csrf, due_id, soon)
    await _schedule(client, editor_csrf, held_id, soon)
    await _schedule(client, editor_csrf, waiting_id, soon)

    past = datetime.now(UTC) - timedelta(minutes=5)
    due = await _row(db, due_id)
    due.publish_at = past
    held = await _row(db, held_id)
    held.publish_at = past
    held.legal_hold = True
    await db.commit()

    assert (await client.get("/en/article/due-briefing")).status_code == 404
    assert await publish_scheduled(db) == 1
    assert await publish_scheduled(db) == 0

    live = await client.get("/en/article/due-briefing")
    assert live.status_code == 200
    assert "Due briefing" in live.text
    home = await client.get("/en/")
    assert "Due briefing" in home.text
    assert "Held briefing" not in home.text
    assert "Waiting briefing" not in home.text
    assert (await client.get("/en/article/held-briefing")).status_code == 404
    assert (await client.get("/en/article/waiting-briefing")).status_code == 404
    assert (await _row(db, held_id)).status.value == "scheduled"
    assert (await _row(db, waiting_id)).status.value == "scheduled"

    event = await db.scalar(
        select(AuditEvent).where(
            AuditEvent.entity_id == due_id, AuditEvent.action == "article.publish"
        )
    )
    assert event is not None
    assert event.actor_id is None
    assert event.after == {"status": "published", "via": "scheduler"}

    published = await _row(db, due_id)
    published.unpublish_at = past
    await db.commit()
    assert await publish_scheduled(db) == 1
    assert await publish_scheduled(db) == 0
    assert (await client.get("/en/article/due-briefing")).status_code == 410
    assert "Due briefing" not in (await client.get("/en/")).text
    takedown = await db.scalar(
        select(AuditEvent).where(
            AuditEvent.entity_id == due_id, AuditEvent.action == "article.unpublish"
        )
    )
    assert takedown is not None
    assert takedown.actor_id is None
    assert takedown.after == {"status": "unpublished", "via": "scheduler"}
