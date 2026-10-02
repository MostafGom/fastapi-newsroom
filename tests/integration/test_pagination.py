import base64
import re

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


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


async def test_media_library_filters_by_name_and_keeps_a_file_in_use(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    section = await _section(db, "media-desk")
    editor = await make_staff("editor", section_id=section.id)
    csrf = await api_login(client, editor)
    author = await author_for_user(db, editor.id)  # type: ignore[arg-type]
    assert author is not None
    headers = {"x-csrf-token": csrf}

    async def upload(name: str) -> str:
        uploaded = await client.post(
            "/api/v1/admin/media",
            files={"file": (name, PNG, "image/png")},
            headers=headers,
        )
        assert uploaded.status_code == 200, uploaded.text
        return uploaded.json()["id"]

    chamber = await upload("chamber.png")
    other = await upload("other.png")
    exact = await upload("room_one.png")
    decoy = await upload("roomxone.png")

    named = await client.get("/admin/media", params={"q": "chamber"})
    assert named.status_code == 200
    assert chamber in named.text
    assert other not in named.text
    assert 'name="q" value="chamber"' in named.text
    assert "upload-preview" in named.text
    assert "createObjectURL" in named.text
    assert "AbortController" in named.text
    assert "إلغاء" in named.text
    assert "إيقاف" in named.text

    wildcard = await client.get("/admin/media", params={"q": "room_one"})
    assert exact in wildcard.text
    assert decoy not in wildcard.text

    missing = await client.get("/admin/media", params={"q": "zzzz-absent"})
    assert "لا صور بهذا الاسم." in missing.text
    assert "media-grid" not in missing.text

    refused = await client.post(
        f"/admin/media/{chamber}/name",
        data={
            "csrf_token": _csrf(named.text),
            "filename": "   ",
            "credit": "Desk",
            "q": "chamber",
            "page": "1",
        },
    )
    assert refused.status_code == 303
    assert "notice=error" in refused.headers["location"]
    assert "q=chamber" in refused.headers["location"]
    shown = await client.get(refused.headers["location"])
    assert "Image name is empty" in shown.text

    saved = await client.post(
        f"/admin/media/{chamber}/name",
        data={
            "csrf_token": _csrf(shown.text),
            "filename": "chamber.png",
            "credit": "Reuters",
            "q": "chamber",
            "page": "1",
        },
        follow_redirects=True,
    )
    assert saved.status_code == 200
    assert 'value="Reuters"' in saved.text
    assert "تم الحفظ." in saved.text

    created = await client.post(
        "/api/v1/admin/articles",
        headers=headers,
        json={
            "section_id": str(section.id),
            "author_ids": [str(author.id)],
            "locale": "en",
            "slug": "media-lead",
            "content": {"title": "Lead", "body": _doc("Lead")},
        },
    )
    assert created.status_code == 201, created.text
    lead = await client.put(
        f"/api/v1/admin/articles/{created.json()['id']}/lead",
        headers=headers,
        json={"media_id": chamber},
    )
    assert lead.status_code == 204, lead.text
    held = await client.get("/admin/media", params={"q": "chamber"})
    assert "مستخدمة في مادة." in held.text
    assert f"/admin/media/{chamber}/delete" not in held.text
    free = await client.get("/admin/media", params={"q": "other"})
    assert f"/admin/media/{other}/delete" in free.text


async def test_story_picks_images_from_the_library(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    section = await _section(db, "picker-desk")
    editor = await make_staff("editor", section_id=section.id)
    csrf = await api_login(client, editor)
    author = await author_for_user(db, editor.id)  # type: ignore[arg-type]
    assert author is not None
    headers = {"x-csrf-token": csrf}

    async def upload(name: str) -> str:
        uploaded = await client.post(
            "/api/v1/admin/media",
            files={"file": (name, PNG, "image/png")},
            headers=headers,
        )
        assert uploaded.status_code == 200, uploaded.text
        return uploaded.json()["id"]

    chamber = await upload("chamber.png")
    other = await upload("other.png")

    lead = await client.get(
        "/admin/media/picker", params={"q": "chamber", "mode": "lead", "locale": "en"}
    )
    assert lead.status_code == 200
    assert chamber in lead.text
    assert other not in lead.text
    bare = re.search(rf'<button[^>]*data-pick="{chamber}"[^>]*>', lead.text)
    assert bare is not None
    assert "disabled" not in bare.group(0)

    blocked = await client.get(
        "/admin/media/picker", params={"q": "chamber", "mode": "body", "locale": "en"}
    )
    waiting = re.search(rf'<button[^>]*data-pick="{chamber}"[^>]*>', blocked.text)
    assert waiting is not None
    assert "disabled" in waiting.group(0)
    assert "أضف النص البديل" in blocked.text

    caption = await client.put(
        f"/api/v1/admin/media/{chamber}/translations",
        headers=headers,
        json={"locale": "en", "caption": "The chamber", "alt_text": "Chamber"},
    )
    assert caption.status_code == 200, caption.text
    ready = await client.get(
        "/admin/media/picker", params={"q": "chamber", "mode": "body", "locale": "en"}
    )
    choice = re.search(rf'<button[^>]*data-pick="{chamber}"[^>]*>', ready.text)
    assert choice is not None
    assert 'data-alt="Chamber"' in choice.group(0)
    assert "disabled" not in choice.group(0)

    story_id = await _create(client, csrf, str(section.id), str(author.id), "picker-story")
    story = await client.get(f"/admin/stories/{story_id}")
    assert story.status_code == 200
    assert '<select name="media_id">' not in story.text
    assert 'name="media_id"' in story.text
    assert "/admin/media/picker?mode=lead" in story.text
    assert 'id="body-media"' in story.text
    assert 'id="body-media-upload"' in story.text
    assert 'id="body-media-file"' in story.text
    assert 'data-locale="en"' in story.text
