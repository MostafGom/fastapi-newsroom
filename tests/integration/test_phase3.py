import base64
import re

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.newsletters.models import NewsletterIssue
from newsroom.newsletters.service import NewsletterService
from newsroom.seed.demo import DEMO_PASSWORD, READER_EMAIL, seed_demo
from tests.conftest import StaffAccount, api_login

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
CSRF_FIELD = re.compile(r'name="csrf_token" value="([^"]+)"')


def _csrf(html: str) -> str:
    match = CSRF_FIELD.search(html)
    assert match is not None
    return match.group(1)


def _article_id(payload: dict, slug: str) -> str:
    for article in payload["items"]:
        for item in article["localizations"]:
            if item["slug"] == slug:
                return article["id"]
    raise AssertionError(f"missing article {slug}")


async def test_media_comments_and_briefing(client: AsyncClient, db: AsyncSession) -> None:
    await seed_demo(db)
    editor = StaffAccount(id=None, email="demo-editor@example.com", password=DEMO_PASSWORD)
    token = await api_login(client, editor)
    headers = {"X-CSRF-Token": token}

    uploaded = await client.post(
        "/api/v1/admin/media",
        files={"file": ("dot.png", PNG, "image/png")},
        data={"credit": "Desk"},
        headers=headers,
    )
    assert uploaded.status_code == 200, uploaded.text
    asset = uploaded.json()
    assert asset["width"] == 1
    assert asset["mime_type"] == "image/png"
    assert asset["filename"] == "dot.png"
    assert asset["translations"] == []
    renamed = await client.put(
        f"/api/v1/admin/media/{asset['id']}/name",
        json={"filename": "../../chamber photo.png"},
        headers=headers,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["filename"] == "chamber photo.png"
    image = await client.get(f"/media/{asset['id']}")
    assert image.status_code == 200
    assert image.content.startswith(b"\xff\xd8")
    original = await client.get(f"/media/{asset['id']}/original")
    assert original.content.startswith(b"\x89PNG")

    library = await client.get("/admin/media")
    assert library.status_code == 200
    assert asset["id"] in library.text
    caption = await client.put(
        f"/api/v1/admin/media/{asset['id']}/translations",
        json={"locale": "en", "caption": "The chamber", "alt_text": "Chamber"},
        headers=headers,
    )
    assert caption.status_code == 200, caption.text

    listed = await client.get("/api/v1/admin/articles")
    lead = await client.put(
        f"/api/v1/admin/articles/{_article_id(listed.json(), 'cabinet-budget')}/lead",
        json={"media_id": asset["id"]},
        headers=headers,
    )
    assert lead.status_code == 204, lead.text
    story_page = await client.get("/en/article/cabinet-budget")
    assert f"/media/{asset['id']}" in story_page.text
    assert "The chamber" in story_page.text

    home = await client.get("/en/")
    assert home.status_code == 200
    assert "Cabinet approves the 2027 budget" in home.text
    assert "Budget desk" not in home.text

    form = await client.get("/en/login")
    await client.post(
        "/en/login",
        data={"csrf_token": _csrf(form.text), "email": READER_EMAIL, "password": DEMO_PASSWORD},
    )
    story = await client.get("/en/article/cabinet-budget")
    posted = await client.post(
        "/en/article/cabinet-budget/comments",
        data={"csrf_token": _csrf(story.text), "body": "The deficit figure needs a source."},
    )
    assert posted.status_code == 303
    visible = await client.get("/en/article/cabinet-budget")
    assert "The deficit figure needs a source." in visible.text
    assert "Nour Reader" in visible.text
    remove = re.search(r'action="([^"]+/hide)"', visible.text)
    assert remove is not None
    hidden = await client.post(remove.group(1), data={"csrf_token": _csrf(visible.text)})
    assert hidden.status_code == 303
    cleared = await client.get("/en/article/cabinet-budget")
    assert "The deficit figure needs a source." not in cleared.text

    account = await client.get("/en/account")
    await client.post(
        "/en/account",
        data={
            "csrf_token": _csrf(account.text),
            "display_name": "Nour Reader",
            "preferred_locale": "en",
            "newsletter_opt_in": "1",
        },
    )
    sent: list[str] = []
    assert (
        await NewsletterService(db).send_due(deliver=lambda _to, _subject, body: sent.append(body))
        == 1
    )
    assert sent
    assert "/en/article/writer-culture-note" in sent[0]
    issue = await db.scalar(select(NewsletterIssue).where(NewsletterIssue.locale == "en"))
    assert issue is not None
    assert "writer-culture-note" in issue.story_slugs
    assert await NewsletterService(db).send_due() == 0
