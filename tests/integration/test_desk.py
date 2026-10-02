import base64
import json
import re
import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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
    assert "Cabinet meets" in desk.text

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
