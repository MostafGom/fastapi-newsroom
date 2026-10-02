"""Ownership, legal hold, autosave, purge, and the remaining admin controls."""

import base64
import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.articles.models import ArticleRevision
from newsroom.articles.service import author_for_user
from newsroom.taxonomy.schemas import (
    SectionCreate,
    SectionTranslationIn,
    TagCreate,
    TagTranslationIn,
)
from newsroom.taxonomy.service import TaxonomyService
from tests.conftest import MakeStaff, api_login

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _doc(text: str) -> dict:
    paragraph = {"type": "paragraph", "content": [{"type": "text", "text": text}]}
    return {"type": "doc", "content": [paragraph]}


async def _section(db: AsyncSession, key: str):
    return await TaxonomyService(db).create_section(
        SectionCreate(
            key=key,
            translations=[SectionTranslationIn(locale="en", name=key, slug=key)],
        )
    )


async def _create(
    client: AsyncClient, csrf: str, section_id: str, author_id: str, slug: str
) -> str:
    created = await client.post(
        "/api/v1/admin/articles",
        headers={"x-csrf-token": csrf},
        json={
            "section_id": section_id,
            "author_ids": [author_id],
            "locale": "en",
            "slug": slug,
            "content": {"title": slug, "body": _doc(slug)},
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["localizations"][0]["id"]


async def test_a_writer_cannot_submit_or_delete_someone_elses_draft(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    section = await _section(db, "ownership-desk")
    owner = await make_staff("writer")
    other = await make_staff("writer")
    editor = await make_staff("editor", section_id=section.id)
    author = await author_for_user(db, owner.id)  # type: ignore[arg-type]
    assert author is not None
    csrf = await api_login(client, owner)
    own_id = await _create(client, csrf, str(section.id), str(author.id), "owned-draft")
    foreign_id = await _create(client, csrf, str(section.id), str(author.id), "foreign-draft")

    client.cookies.clear()
    other_csrf = await api_login(client, other)
    denied_delete = await client.delete(
        f"/api/v1/admin/localizations/{foreign_id}",
        headers={"x-csrf-token": other_csrf},
    )
    denied_submit = await client.post(
        f"/api/v1/admin/localizations/{foreign_id}/transitions",
        headers={"x-csrf-token": other_csrf},
        json={"action": "submit", "lock_version": 1},
    )
    assert denied_delete.status_code == 403
    assert denied_submit.status_code == 403

    client.cookies.clear()
    editor_csrf = await api_login(client, editor)
    removed = await client.delete(
        f"/api/v1/admin/localizations/{foreign_id}",
        headers={"x-csrf-token": editor_csrf},
    )
    assert removed.status_code == 204

    client.cookies.clear()
    csrf = await api_login(client, owner)
    submitted = await client.post(
        f"/api/v1/admin/localizations/{own_id}/transitions",
        headers={"x-csrf-token": csrf},
        json={"action": "submit", "lock_version": 1},
    )
    assert submitted.status_code == 200


async def test_legal_hold_blocks_publish_until_counsel_is_recorded(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    section = await _section(db, "legal-desk")
    writer = await make_staff("writer")
    editor = await make_staff("editor", section_id=section.id)
    author = await author_for_user(db, writer.id)  # type: ignore[arg-type]
    assert author is not None
    csrf = await api_login(client, writer)
    localization_id = await _create(client, csrf, str(section.id), str(author.id), "held-story")
    submitted = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/transitions",
        headers={"x-csrf-token": csrf},
        json={"action": "submit", "lock_version": 1},
    )
    assert submitted.status_code == 200

    client.cookies.clear()
    editor_csrf = await api_login(client, editor)
    approved = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/transitions",
        headers={"x-csrf-token": editor_csrf},
        json={"action": "approve", "lock_version": 2, "reason": "breaking, copy to follow"},
    )
    assert approved.status_code == 200, approved.text
    held = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/legal-hold",
        headers={"x-csrf-token": editor_csrf},
        json={"reason": "counsel has not signed off"},
    )
    assert held.status_code == 204, held.text
    blocked = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/transitions",
        headers={"x-csrf-token": editor_csrf},
        json={"action": "publish", "lock_version": 3},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "legal_hold"
    cleared = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/legal-hold/clear",
        headers={"x-csrf-token": editor_csrf},
        json={"reason": "counsel signed off"},
    )
    assert cleared.status_code == 204
    published = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/transitions",
        headers={"x-csrf-token": editor_csrf},
        json={"action": "publish", "lock_version": 3},
    )
    assert published.status_code == 200, published.text
    taken = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/transitions",
        headers={"x-csrf-token": editor_csrf},
        json={
            "action": "unpublish",
            "lock_version": published.json()["lock_version"],
            "reason": "counsel asked for it down",
            "takedown_reason": "legal",
        },
    )
    assert taken.status_code == 200, taken.text
    held_again = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/legal-hold",
        headers={"x-csrf-token": editor_csrf},
        json={"reason": "counsel has not cleared a return"},
    )
    assert held_again.status_code == 204, held_again.text
    blocked_again = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/transitions",
        headers={"x-csrf-token": editor_csrf},
        json={"action": "republish", "lock_version": taken.json()["lock_version"]},
    )
    assert blocked_again.status_code == 409
    assert blocked_again.json()["code"] == "legal_hold"
    page = await client.get(f"/admin/stories/{localization_id}")
    assert page.status_code == 200
    assert "article.clear_legal" in page.text
    assert "article.publish" in page.text


async def test_autosave_replaces_the_open_row_until_the_window_closes(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    section = await _section(db, "autosave-desk")
    writer = await make_staff("writer")
    author = await author_for_user(db, writer.id)  # type: ignore[arg-type]
    assert author is not None
    csrf = await api_login(client, writer)
    localization_id = await _create(client, csrf, str(section.id), str(author.id), "autosaved")
    current = await client.get(f"/api/v1/admin/localizations/{localization_id}")
    base = current.json()["current_revision"]["id"]
    headers = {"x-csrf-token": csrf}

    async def save(base_id: str, title: str) -> dict:
        response = await client.post(
            f"/api/v1/admin/localizations/{localization_id}/revisions",
            headers=headers,
            json={
                "base_revision_id": base_id,
                "kind": "autosave",
                "content": {"title": title, "body": _doc(title)},
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    first = await save(base, "Draft one")
    second = await save(first["id"], "Draft two")
    assert second["id"] == first["id"]
    assert second["revision_no"] == first["revision_no"]
    listed = await client.get(f"/api/v1/admin/localizations/{localization_id}/revisions")
    assert len(listed.json()["items"]) == 2

    row = await db.get(ArticleRevision, uuid.UUID(first["id"]))
    assert row is not None
    row.created_at = datetime.now(UTC) - timedelta(minutes=10)
    await db.commit()
    third = await save(first["id"], "Draft three")
    assert third["id"] != first["id"]


async def test_purge_removes_the_edition_and_keeps_the_audit_row(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    section = await _section(db, "purge-desk")
    writer = await make_staff("writer")
    editor = await make_staff("editor", section_id=section.id)
    super_admin = await make_staff("super_admin")
    author = await author_for_user(db, writer.id)  # type: ignore[arg-type]
    assert author is not None
    csrf = await api_login(client, writer)
    localization_id = await _create(client, csrf, str(section.id), str(author.id), "purge-me")
    await client.post(
        f"/api/v1/admin/localizations/{localization_id}/transitions",
        headers={"x-csrf-token": csrf},
        json={"action": "submit", "lock_version": 1},
    )
    client.cookies.clear()
    editor_csrf = await api_login(client, editor)
    await client.post(
        f"/api/v1/admin/localizations/{localization_id}/transitions",
        headers={"x-csrf-token": editor_csrf},
        json={"action": "approve", "lock_version": 2, "reason": "breaking"},
    )
    await client.post(
        f"/api/v1/admin/localizations/{localization_id}/transitions",
        headers={"x-csrf-token": editor_csrf},
        json={"action": "publish", "lock_version": 3},
    )
    forbidden = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/purge",
        headers={"x-csrf-token": editor_csrf},
        json={"reason": "court order 12"},
    )
    assert forbidden.status_code == 403
    client.cookies.clear()
    admin_csrf = await api_login(client, super_admin)
    purged = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/purge",
        headers={"x-csrf-token": admin_csrf},
        json={"reason": "court order 12"},
    )
    assert purged.status_code == 204, purged.text
    missing = await client.get("/en/article/purge-me")
    assert missing.status_code == 404
    audit = await client.get("/api/v1/admin/audit-events", params={"action": "article.purge"})
    assert audit.status_code == 200
    assert any(item["reason"] == "court order 12" for item in audit.json()["items"])


async def test_tag_merge_media_delete_guest_byline_locale_role_and_registration(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    section = await _section(db, "controls-desk")
    writer = await make_staff("writer")
    editor = await make_staff("editor", section_id=section.id)
    admin = await make_staff("admin")
    super_admin = await make_staff("super_admin")
    author = await author_for_user(db, writer.id)  # type: ignore[arg-type]
    assert author is not None
    source = await TaxonomyService(db).create_tag(
        TagCreate(
            key="old-tag",
            translations=[TagTranslationIn(locale="en", name="Old", slug="old-tag")],
        )
    )
    target = await TaxonomyService(db).create_tag(
        TagCreate(
            key="new-tag",
            translations=[TagTranslationIn(locale="en", name="New", slug="new-tag")],
        )
    )
    csrf = await api_login(client, writer)
    created = await client.post(
        "/api/v1/admin/articles",
        headers={"x-csrf-token": csrf},
        json={
            "section_id": str(section.id),
            "author_ids": [str(author.id)],
            "tag_ids": [str(source.id)],
            "locale": "en",
            "slug": "tagged-story",
            "content": {"title": "Tagged", "body": _doc("Tagged")},
        },
    )
    assert created.status_code == 201, created.text
    article_id = created.json()["id"]

    client.cookies.clear()
    editor_csrf = await api_login(client, editor)
    merged = await client.post(
        "/api/v1/admin/tags/merge",
        headers={"x-csrf-token": editor_csrf},
        json={"source_id": str(source.id), "target_id": str(target.id)},
    )
    assert merged.status_code == 200, merged.text
    db.expire_all()
    article = await client.get(f"/api/v1/admin/articles/{article_id}")
    assert article.json()["tag_ids"] == [str(target.id)]

    uploaded = await client.post(
        "/api/v1/admin/media",
        headers={"x-csrf-token": editor_csrf},
        files={"file": ("dot.png", PNG, "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    asset_id = uploaded.json()["id"]
    removed = await client.delete(
        f"/api/v1/admin/media/{asset_id}",
        headers={"x-csrf-token": editor_csrf},
    )
    assert removed.status_code == 204, removed.text
    gone = await client.get(f"/media/{asset_id}")
    assert gone.status_code == 404

    guest = await client.post(
        "/api/v1/admin/authors",
        headers={"x-csrf-token": editor_csrf},
        json={
            "kind": "contributor",
            "key": "wire-guest",
            "translations": [{"locale": "en", "display_name": "Wire Guest", "slug": "wire-guest"}],
        },
    )
    assert guest.status_code == 201, guest.text

    client.cookies.clear()
    admin_csrf = await api_login(client, admin)
    added = await client.post(
        "/api/v1/admin/locales",
        headers={"x-csrf-token": admin_csrf},
        json={"code": "fr", "name": "French", "native_name": "Français", "direction": "ltr"},
    )
    assert added.status_code == 201, added.text
    home = await client.get("/fr/")
    assert home.status_code == 200
    hidden = await client.post(
        "/api/v1/admin/locales/fr/enabled",
        headers={"x-csrf-token": admin_csrf},
        params={"enabled": "false"},
    )
    assert hidden.status_code == 200, hidden.text
    missing = await client.get("/fr/")
    assert missing.status_code == 404

    client.cookies.clear()
    super_csrf = await api_login(client, super_admin)
    role = await client.post(
        "/api/v1/admin/roles",
        headers={"x-csrf-token": super_csrf},
        json={
            "key": "proofreader",
            "name": "Proofreader",
            "rank": 12,
            "permissions": ["article.read"],
        },
    )
    assert role.status_code == 201, role.text
    renamed = await client.patch(
        f"/api/v1/admin/roles/{role.json()['id']}",
        headers={"x-csrf-token": super_csrf},
        json={"name": "Proof desk"},
    )
    assert renamed.status_code == 200
    roles = await client.get("/api/v1/admin/roles")
    writer_role = next(item for item in roles.json() if item["key"] == "writer")
    locked = await client.patch(
        f"/api/v1/admin/roles/{writer_role['id']}",
        headers={"x-csrf-token": super_csrf},
        json={"name": "Renamed writer"},
    )
    assert locked.status_code == 409
    client.cookies.clear()
    writer_csrf = await api_login(client, writer)
    denied = await client.post(
        "/api/v1/admin/roles",
        headers={"x-csrf-token": writer_csrf},
        json={"key": "intern", "name": "Intern", "rank": 5, "permissions": ["article.read"]},
    )
    assert denied.status_code == 403

    client.cookies.clear()
    super_csrf = await api_login(client, super_admin)
    closed = await client.put(
        "/api/v1/admin/settings",
        headers={"x-csrf-token": super_csrf},
        json={"site_name": "Desk", "registration_enabled": False},
    )
    assert closed.status_code == 200, closed.text
    client.cookies.clear()
    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": "new-reader@example.com", "password": "correct-horse-battery"},
    )
    assert registered.status_code == 403
