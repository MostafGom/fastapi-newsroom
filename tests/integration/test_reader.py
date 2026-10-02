import re

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.articles.models import Article
from newsroom.seed.demo import DEMO_PASSWORD, READER_EMAIL, seed_demo

CSRF_FIELD = re.compile(r'name="csrf_token" value="([^"]+)"')


def _csrf(html: str) -> str:
    match = CSRF_FIELD.search(html)
    assert match is not None
    return match.group(1)


async def test_seed_demo_publishes_once(db: AsyncSession, client: AsyncClient) -> None:
    first = await seed_demo(db)
    second = await seed_demo(db)
    assert any(line.startswith("created ") for line in first)
    assert not any(line.startswith("created ") for line in second)
    assert await db.scalar(select(func.count()).select_from(Article)) == 3

    home = await client.get("/en/")
    assert home.status_code == 200
    assert "Cabinet approves the 2027 budget" in home.text
    assert "Read the full article" in home.text
    assert "story-card-lead" in home.text
    assert "story-fallback" in home.text

    arabic = await client.get("/ar/article/muwazana-2027")
    assert arabic.status_code == 200
    assert "الحكومة تقر موازنة 2027" in arabic.text

    draft = await client.get("/ar/article/maswada-qanun")
    assert draft.status_code == 404

    tagged = await client.get("/en/tag/budget")
    assert tagged.status_code == 200
    assert "Budget" in tagged.text
    assert "Cabinet approves the 2027 budget" in tagged.text
    assert "Embargoed briefing" not in tagged.text

    arabic_tag = await client.get("/ar/tag/muwazana")
    assert arabic_tag.status_code == 200
    assert "الحكومة تقر موازنة 2027" in arabic_tag.text
    assert "مسودة" not in arabic_tag.text

    missing_tag = await client.get("/en/tag/muwazana")
    assert missing_tag.status_code == 404

    story = await client.get("/en/article/cabinet-budget")
    assert 'href="/en/tag/budget"' in story.text


async def test_reader_updates_profile_and_bookmarks(db: AsyncSession, client: AsyncClient) -> None:
    await seed_demo(db)
    form = await client.get("/en/login")
    logged_in = await client.post(
        "/en/login",
        data={"csrf_token": _csrf(form.text), "email": READER_EMAIL, "password": DEMO_PASSWORD},
    )
    assert logged_in.status_code == 303
    assert logged_in.headers["location"] == "/en/account"

    account = await client.get("/en/account")
    assert account.status_code == 200
    assert "Nour Reader" in account.text
    assert "Cabinet approves the 2027 budget" in account.text

    saved = await client.post(
        "/en/account",
        data={
            "csrf_token": _csrf(account.text),
            "display_name": "Nour Updated",
            "preferred_locale": "en",
            "newsletter_opt_in": "1",
        },
    )
    assert saved.status_code == 303
    updated = await client.get("/en/account")
    assert "Nour Updated" in updated.text

    remove = re.search(r'action="(/en/account/bookmarks/[^"]+/remove)"', updated.text)
    assert remove is not None
    cleared = await client.post(remove.group(1), data={"csrf_token": _csrf(updated.text)})
    assert cleared.status_code == 303
    empty = await client.get("/en/account")
    assert "Cabinet approves the 2027 budget" not in empty.text

    story = await client.get("/en/article/cabinet-budget")
    assert "Bookmark" in story.text
    marked = await client.post(
        "/en/article/cabinet-budget/bookmark",
        data={"csrf_token": _csrf(story.text)},
    )
    assert marked.status_code == 303
    restored = await client.get("/en/account")
    assert "Cabinet approves the 2027 budget" in restored.text
