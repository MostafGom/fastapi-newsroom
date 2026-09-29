from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.articles.service import author_for_user
from newsroom.taxonomy.schemas import SectionCreate, SectionTranslationIn
from newsroom.taxonomy.service import TaxonomyService
from tests.conftest import MakeStaff, api_login


def _doc(text: str) -> dict:
    paragraph = {"type": "paragraph", "content": [{"type": "text", "text": text}]}
    return {"type": "doc", "content": [paragraph]}


async def _create(
    client: AsyncClient, csrf: str, section_id: str, author_id: str, slug: str, title: str
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
    return created.json()["localizations"][0]["id"]


async def test_unpublished_draft_can_be_deleted_and_a_live_story_cannot(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    section = await TaxonomyService(db).create_section(
        SectionCreate(
            key="delete-desk",
            translations=[SectionTranslationIn(locale="en", name="Desk", slug="delete-desk")],
        )
    )
    writer = await make_staff("writer")
    editor = await make_staff("editor", section_id=section.id)
    copy_editor = await make_staff("copy_editor")
    author = await author_for_user(db, writer.id)  # type: ignore[arg-type]
    assert author is not None
    section_id = str(section.id)
    author_id = str(author.id)

    csrf = await api_login(client, writer)
    draft_id = await _create(client, csrf, section_id, author_id, "delete-me", "Delete me")
    live_id = await _create(client, csrf, section_id, author_id, "keep-me", "Keep me")

    client.cookies.clear()
    copy_csrf = await api_login(client, copy_editor)
    forbidden = await client.delete(
        f"/api/v1/admin/localizations/{draft_id}",
        headers={"x-csrf-token": copy_csrf},
    )
    assert forbidden.status_code == 403

    client.cookies.clear()
    csrf = await api_login(client, writer)
    deleted = await client.delete(
        f"/api/v1/admin/localizations/{draft_id}",
        headers={"x-csrf-token": csrf},
    )
    assert deleted.status_code == 204
    missing = await client.get(f"/api/v1/admin/localizations/{draft_id}")
    assert missing.status_code == 404
    listed = await client.get("/api/v1/admin/articles")
    titles = [
        item["title"] for article in listed.json()["items"] for item in article["localizations"]
    ]
    assert "Delete me" not in titles
    assert "Keep me" in titles

    submitted = await client.post(
        f"/api/v1/admin/localizations/{live_id}/transitions",
        headers={"x-csrf-token": csrf},
        json={"action": "submit", "lock_version": 1},
    )
    assert submitted.status_code == 200, submitted.text

    client.cookies.clear()
    editor_csrf = await api_login(client, editor)
    approved = await client.post(
        f"/api/v1/admin/localizations/{live_id}/transitions",
        headers={"x-csrf-token": editor_csrf},
        json={"action": "approve", "lock_version": 2, "reason": "copy already done"},
    )
    assert approved.status_code == 200, approved.text
    published = await client.post(
        f"/api/v1/admin/localizations/{live_id}/transitions",
        headers={"x-csrf-token": editor_csrf},
        json={"action": "publish", "lock_version": 3},
    )
    assert published.status_code == 200, published.text

    refused = await client.delete(
        f"/api/v1/admin/localizations/{live_id}",
        headers={"x-csrf-token": editor_csrf},
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "illegal_transition"
    still_there = await client.get(f"/api/v1/admin/localizations/{live_id}")
    assert still_there.status_code == 200
    assert still_there.json()["status"] == "published"
