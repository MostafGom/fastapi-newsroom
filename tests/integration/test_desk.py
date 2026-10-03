import base64
import json
import re
import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.articles.service import author_for_user
from newsroom.taxonomy.schemas import SectionCreate, SectionTranslationIn
from newsroom.taxonomy.service import TaxonomyService
from tests.conftest import MakeStaff, StaffAccount

CSRF_FIELD = re.compile(r'name="csrf_token" value="([^"]+)"')
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
BODY = {
    "type": "doc",
    "content": [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "The cabinet met overnight."}],
        }
    ],
}


def _csrf(html: str) -> str:
    match = CSRF_FIELD.search(html)
    assert match is not None
    return match.group(1)


async def _login(client: AsyncClient, account: StaffAccount) -> None:
    client.cookies.clear()
    form = await client.get("/admin/login")
    response = await client.post(
        "/admin/login",
        data={"csrf_token": _csrf(form.text), "email": account.email, "password": account.password},
    )
    assert response.status_code == 303


async def test_desk_publishes_a_story(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    section = await TaxonomyService(db).create_section(
        SectionCreate(
            key="desk-politics",
            translations=[
                SectionTranslationIn(locale="en", name="Politics", slug="desk-politics"),
                SectionTranslationIn(locale="ar", name="سياسة", slug="desk-siyasa"),
            ],
        )
    )
    writer = await make_staff("writer")
    editor = await make_staff("editor", section_id=section.id)
    copy_editor = await make_staff("copy_editor")

    await _login(client, writer)
    form = await client.get("/admin/stories/new?locale=en")
    assert form.status_code == 200
    assert 'value="publish"' not in form.text
    assert "data-lead-picker" in form.text
    assert 'name="lead_media_id"' in form.text
    created = await client.post(
        "/admin/stories/new",
        data={
            "csrf_token": _csrf(form.text),
            "section_id": str(section.id),
            "locale": "en",
            "slug": "desk-cabinet",
            "title": "Cabinet meets",
            "article_type": "news",
            "body": json.dumps(BODY),
        },
    )
    assert created.status_code == 303, created.text
    story_url = created.headers["location"].split("?")[0]

    desk = await client.get("/admin/")
    assert "Cabinet meets" not in desk.text
    assert 'href="/admin/stories"' in desk.text
    listed = await client.get("/admin/stories")
    assert "Cabinet meets" in listed.text

    page = await client.get(story_url)
    assert page.status_code == 200
    assert 'value="submit"' in page.text
    assert 'value="publish"' not in page.text
    assert "يرسل النسخة إلى محرر المكتب" in page.text
    assert "تنقل هذه الخطوات النسخة بين الكاتب" in page.text
    assert 'name="publish_at"' not in page.text
    submitted = await client.post(
        f"{story_url}/transition",
        data={"csrf_token": _csrf(page.text), "action": "submit", "lock_version": "1"},
    )
    assert submitted.status_code == 303
    assert "notice=error" not in submitted.headers["location"]

    await _login(client, editor)
    review = await client.get(story_url)
    assert 'value="send_to_copy"' in review.text
    sent = await client.post(
        f"{story_url}/transition",
        data={
            "csrf_token": _csrf(review.text),
            "action": "send_to_copy",
            "lock_version": "2",
        },
    )
    assert sent.status_code == 303
    assert "notice=error" not in sent.headers["location"]

    await _login(client, copy_editor)
    copy_page = await client.get(story_url)
    assert 'value="finish_copy"' in copy_page.text
    signed = await client.post(
        f"{story_url}/transition",
        data={
            "csrf_token": _csrf(copy_page.text),
            "action": "finish_copy",
            "lock_version": "3",
        },
    )
    assert signed.status_code == 303
    assert "notice=error" not in signed.headers["location"]

    await _login(client, editor)
    approved = await client.get(story_url)
    assert 'value="publish"' in approved.text
    published = await client.post(
        f"{story_url}/transition",
        data={"csrf_token": _csrf(approved.text), "action": "publish", "lock_version": "4"},
    )
    assert published.status_code == 303
    assert "notice=error" not in published.headers["location"]

    live = await client.get(story_url)
    assert 'value="unpublish"' in live.text
    assert "هذا لا يسحب المادة من الموقع" in live.text
    assert "هذا يزيل النسخة من الموقع" in live.text
    assert "ليس وقفاً قانونياً" in live.text

    public = await client.get("/en/article/desk-cabinet")
    assert public.status_code == 200
    assert "Cabinet meets" in public.text
    assert "The cabinet met overnight." in public.text


async def test_new_story_stores_the_lead_image(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    section = await TaxonomyService(db).create_section(
        SectionCreate(
            key="desk-lead",
            translations=[
                SectionTranslationIn(locale="en", name="Lead", slug="desk-lead"),
                SectionTranslationIn(locale="ar", name="صورة", slug="desk-sura"),
            ],
        )
    )
    writer = await make_staff("writer")
    await _login(client, writer)
    form = await client.get("/admin/stories/new?locale=en")
    csrf = _csrf(form.text)
    uploaded = await client.post(
        "/api/v1/admin/media",
        files={"file": ("chamber.png", PNG, "image/png")},
        headers={"x-csrf-token": csrf},
    )
    assert uploaded.status_code == 200, uploaded.text
    asset_id = uploaded.json()["id"]

    created = await client.post(
        "/admin/stories/new",
        data={
            "csrf_token": csrf,
            "section_id": str(section.id),
            "locale": "en",
            "slug": "desk-with-lead",
            "title": "Story with a picture",
            "article_type": "news",
            "body": json.dumps(BODY),
            "lead_media_id": asset_id,
        },
    )
    assert created.status_code == 303, created.text
    story = await client.get(created.headers["location"].split("?")[0])
    assert story.status_code == 200
    assert f'src="/media/{asset_id}"' in story.text
    assert f'value="{asset_id}"' in story.text

    missing = uuid.uuid4()
    refused = await client.post(
        "/admin/stories/new",
        data={
            "csrf_token": csrf,
            "section_id": str(section.id),
            "locale": "en",
            "slug": "desk-missing-lead",
            "title": "Missing picture",
            "article_type": "news",
            "body": json.dumps(BODY),
            "lead_media_id": str(missing),
        },
    )
    assert refused.status_code == 404
    assert str(missing) in refused.text
    assert "Media not found" in refused.text


async def test_desk_sidebar_is_signed_in_only(client: AsyncClient, make_staff: MakeStaff) -> None:
    login = await client.get("/admin/login")
    assert login.status_code == 200
    assert "desk-nav" not in login.text

    await _login(client, await make_staff("writer"))
    desk = await client.get("/admin/")
    assert desk.status_code == 200
    assert 'id="desk-nav"' in desk.text
    assert 'href="/admin/" aria-current="page"' in desk.text
    assert 'href="/admin/stories"' in desk.text
    assert 'href="/admin/stories" aria-current="page"' not in desk.text
    assert 'href="/admin/workflow"' in desk.text
    assert 'href="/admin/workflow" aria-current="page"' not in desk.text

    flow = await client.get("/admin/workflow")
    assert flow.status_code == 200
    assert 'href="/admin/workflow" aria-current="page"' in flow.text


async def test_new_story_starts_in_the_edition_direction(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    await TaxonomyService(db).create_section(
        SectionCreate(
            key="direction-desk",
            translations=[
                SectionTranslationIn(locale="en", name="Direction desk", slug="direction-desk"),
                SectionTranslationIn(locale="ar", name="مكتب الاتجاه", slug="maktab-ittijah"),
            ],
        )
    )
    await _login(client, await make_staff("writer"))
    arabic = await client.get("/admin/stories/new")
    assert arabic.status_code == 200
    assert 'data-dir="rtl"' in arabic.text
    assert 'data-cmd="dir" data-value="ltr"' in arabic.text
    assert 'name="title" required dir="rtl"' in arabic.text

    english = await client.get("/admin/stories/new?locale=en")
    assert 'data-dir="ltr"' in english.text
    assert 'name="title" required dir="ltr"' in english.text


def _lock(html: str) -> str:
    match = re.search(r'name="lock_version" value="(\d+)"', html)
    assert match is not None
    return match.group(1)


async def test_story_list_filters_by_desk_facts(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    section = await TaxonomyService(db).create_section(
        SectionCreate(
            key="filter-desk",
            translations=[
                SectionTranslationIn(locale="en", name="Filter desk", slug="filter-desk"),
                SectionTranslationIn(locale="ar", name="مكتب التصفية", slug="maktab-tasfiya"),
            ],
        )
    )
    writer = await make_staff("writer")
    editor = await make_staff("editor", section_id=section.id)
    copy_editor = await make_staff("copy_editor")
    author = await author_for_user(db, writer.id)  # type: ignore[arg-type]
    assert author is not None

    await _login(client, writer)
    form = await client.get("/admin/stories/new?locale=en")
    created = await client.post(
        "/admin/stories/new",
        data={
            "csrf_token": _csrf(form.text),
            "section_id": str(section.id),
            "locale": "en",
            "slug": "filter-target",
            "title": "Filter target",
            "article_type": "news",
            "body": json.dumps(BODY),
        },
    )
    assert created.status_code == 303, created.text
    story_url = created.headers["location"].split("?")[0]

    home = await client.get("/admin/")
    assert "Filter target" not in home.text
    listed = await client.get("/admin/stories")
    assert listed.status_code == 200
    assert 'href="/admin/stories" aria-current="page"' in listed.text
    assert "Filter target" in listed.text
    assert "مكتب التصفية" in listed.text
    assert "Test writer" in listed.text
    hidden = await client.get("/admin/stories", params={"status": "published"})
    assert "Filter target" not in hidden.text
    by_slug = await client.get("/admin/stories", params={"q": "filter-target"})
    assert "Filter target" in by_slug.text
    missed = await client.get("/admin/stories", params={"q": "no-such-story"})
    assert "Filter target" not in missed.text
    by_writer = await client.get("/admin/stories", params={"author_id": str(author.id)})
    assert "Filter target" in by_writer.text
    by_section = await client.get("/admin/stories", params={"section_id": str(section.id)})
    assert "Filter target" in by_section.text
    today = datetime.now(UTC).date().isoformat()
    dated = await client.get("/admin/stories", params={"updated_from": today, "updated_to": today})
    assert "Filter target" in dated.text
    stale = await client.get("/admin/stories", params={"updated_to": "2000-01-01"})
    assert "Filter target" not in stale.text

    page = await client.get(story_url)
    submitted = await client.post(
        f"{story_url}/transition",
        data={"csrf_token": _csrf(page.text), "action": "submit", "lock_version": _lock(page.text)},
    )
    assert submitted.status_code == 303

    await _login(client, editor)
    review = await client.get(story_url)
    sent = await client.post(
        f"{story_url}/transition",
        data={
            "csrf_token": _csrf(review.text),
            "action": "send_to_copy",
            "lock_version": _lock(review.text),
        },
    )
    assert sent.status_code == 303
    edited = await client.get("/admin/stories", params={"reviewed_by": str(editor.id)})
    assert "Filter target" in edited.text
    assert "Test editor" in edited.text

    await _login(client, copy_editor)
    signing = await client.get(story_url)
    signed = await client.post(
        f"{story_url}/transition",
        data={
            "csrf_token": _csrf(signing.text),
            "action": "finish_copy",
            "lock_version": _lock(signing.text),
        },
    )
    assert signed.status_code == 303
    still = await client.get("/admin/stories", params={"reviewed_by": str(editor.id)})
    assert "Filter target" in still.text
    not_copy = await client.get("/admin/stories", params={"reviewed_by": str(copy_editor.id)})
    assert "Filter target" not in not_copy.text
