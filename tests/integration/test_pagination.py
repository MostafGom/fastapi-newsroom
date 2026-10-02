import base64

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.articles.service import author_for_user
from newsroom.core.schemas import PageParams, encode_cursor
from newsroom.media.service import MediaService
from newsroom.taxonomy.schemas import SectionCreate, SectionTranslationIn
from newsroom.taxonomy.service import TaxonomyService
from tests.conftest import MakeStaff, api_login

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _doc(text: str) -> dict:
    paragraph = {"type": "paragraph", "content": [{"type": "text", "text": text}]}
    return {"type": "doc", "content": [paragraph]}


def _slugs(payload: dict) -> list[str]:
    return [loc["slug"] for article in payload["items"] for loc in article["localizations"]]


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


async def _publish(client: AsyncClient, csrf: str, localization_id: str) -> None:
    for action, lock, extra in (
        ("submit", 1, {}),
        ("approve", 2, {"reason": "ready"}),
        ("publish", 3, {}),
    ):
        moved = await client.post(
            f"/api/v1/admin/localizations/{localization_id}/transitions",
            headers={"x-csrf-token": csrf},
            json={"action": action, "lock_version": lock, **extra},
        )
        assert moved.status_code == 200, moved.text


async def test_public_lists_follow_a_cursor(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    section = await _section(db, "page-desk")
    editor = await make_staff("admin")
    author = await author_for_user(db, editor.id)  # type: ignore[arg-type]
    assert author is not None
    csrf = await api_login(client, editor)
    slugs = ["page-one", "page-two", "page-three"]
    for slug in slugs:
        localization_id = await _create(client, csrf, str(section.id), str(author.id), slug)
        await _publish(client, csrf, localization_id)

    first = await client.get("/api/v1/articles", params={"locale": "en", "limit": 2})
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"]
    second = await client.get(
        "/api/v1/articles",
        params={"locale": "en", "limit": 2, "cursor": body["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    seen = {item["slug"] for item in body["items"]}
    seen.update(item["slug"] for item in second.json()["items"])
    assert seen == set(slugs)
    assert second.json()["next_cursor"] is None

    later = await client.get("/en/section/page-desk?page=2")
    assert later.status_code == 200
    assert 'id="listing"' in later.text
    assert 'href="/en/section/page-desk"' in later.text
    assert "cursor=" not in later.text
    assert "page-one" in later.text
    assert "page-three" in later.text

    fragment = await client.get(
        "/en/section/page-desk",
        params={"page": 2, "cursor": body["next_cursor"]},
        headers={"hx-request": "true"},
    )
    assert fragment.status_code == 200
    assert "<html" not in fragment.text
    assert "page-one" in fragment.text
    assert "page-three" not in fragment.text
    assert 'hx-target="#listing"' in fragment.text

    broken = await client.get("/api/v1/articles", params={"locale": "en", "cursor": "not-a-cursor"})
    assert broken.status_code == 400
    assert broken.json()["code"] == "invalid_cursor"
    missing = await client.get(
        "/api/v1/articles",
        params={"locale": "en", "cursor": encode_cursor({"id": "not-used"})},
    )
    assert missing.status_code == 400
    assert missing.json()["code"] == "invalid_cursor"


async def test_section_editor_pages_only_their_desk(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    own = await _section(db, "own-desk")
    other = await _section(db, "other-desk")
    writer = await make_staff("writer")
    editor = await make_staff("editor", section_id=own.id)
    author = await author_for_user(db, writer.id)  # type: ignore[arg-type]
    assert author is not None
    csrf = await api_login(client, writer)
    for slug in ("own-a", "own-b", "own-c"):
        await _create(client, csrf, str(own.id), str(author.id), slug)
    for slug in ("other-a", "other-b"):
        await _create(client, csrf, str(other.id), str(author.id), slug)

    client.cookies.clear()
    await api_login(client, editor)
    first = await client.get("/api/v1/admin/articles", params={"limit": 2})
    assert first.status_code == 200, first.text
    body = first.json()
    assert _slugs(body) == ["own-c", "own-b"]
    assert body["next_cursor"]
    second = await client.get(
        "/api/v1/admin/articles", params={"limit": 2, "cursor": body["next_cursor"]}
    )
    assert second.status_code == 200, second.text
    assert _slugs(second.json()) == ["own-a"]
    assert second.json()["next_cursor"] is None

    desk = await client.get("/admin/?page=2")
    assert desk.status_code == 200
    assert "own-a" in desk.text
    assert "own-c" in desk.text
    assert "other-a" not in desk.text
    assert "cursor=" not in desk.text

    fragment = await client.get(
        "/admin/",
        params={"page": 2, "cursor": body["next_cursor"]},
        headers={"hx-request": "true"},
    )
    assert fragment.status_code == 200
    assert "<html" not in fragment.text
    assert "own-a" in fragment.text
    assert "own-c" not in fragment.text

    broken = await client.get("/api/v1/admin/articles", params={"cursor": "not-a-cursor"})
    assert broken.status_code == 400
    assert broken.json()["code"] == "invalid_cursor"


async def test_media_library_follows_a_cursor(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    editor = await make_staff("editor")
    csrf = await api_login(client, editor)
    ids = []
    for name in ("first.png", "second.png"):
        uploaded = await client.post(
            "/api/v1/admin/media",
            files={"file": (name, PNG, "image/png")},
            headers={"x-csrf-token": csrf},
        )
        assert uploaded.status_code == 200, uploaded.text
        ids.append(uploaded.json()["id"])

    page = await MediaService(db).list_page(PageParams(limit=1, cursor=None))
    assert [str(item.id) for item in page.items] == [ids[1]]
    assert page.next_cursor
    follow = await MediaService(db).list_page(PageParams(limit=1, cursor=page.next_cursor))
    assert [str(item.id) for item in follow.items] == [ids[0]]
    assert follow.next_cursor is None

    library = await client.get(
        "/admin/media",
        params={"page": 2, "cursor": page.next_cursor},
        headers={"hx-request": "true"},
    )
    assert library.status_code == 200
    assert "<html" not in library.text
    assert ids[0] in library.text
    assert ids[1] not in library.text

    broken = await client.get(
        "/admin/media?cursor=not-a-cursor",
        headers={"hx-request": "true"},
    )
    assert broken.status_code == 400
