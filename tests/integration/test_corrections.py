import re

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.seed.demo import DEMO_PASSWORD, seed_demo
from tests.conftest import StaffAccount, api_login

CSRF_FIELD = re.compile(r'name="csrf_token" value="([^"]+)"')


def _csrf(html: str) -> str:
    match = CSRF_FIELD.search(html)
    assert match is not None
    return match.group(1)


def _localization_id(payload: dict, slug: str) -> str:
    for article in payload["items"]:
        for item in article["localizations"]:
            if item["slug"] == slug:
                return item["id"]
    raise AssertionError(f"missing localization {slug}")


async def test_a_published_slug_redirects_and_a_correction_is_public(
    client: AsyncClient, db: AsyncSession
) -> None:
    await seed_demo(db)
    editor = StaffAccount(id=None, email="demo-editor@example.com", password=DEMO_PASSWORD)
    writer = StaffAccount(id=None, email="demo-writer@example.com", password=DEMO_PASSWORD)
    await api_login(client, editor)
    listed = await client.get("/api/v1/admin/articles")
    assert listed.status_code == 200, listed.text
    localization_id = _localization_id(listed.json(), "cabinet-budget")

    page = await client.get(f"/admin/stories/{localization_id}")
    assert page.status_code == 200
    changed = await client.post(
        f"/admin/stories/{localization_id}/slug",
        data={"csrf_token": _csrf(page.text), "slug": "cabinet-budget-2027"},
        follow_redirects=True,
    )
    assert changed.status_code == 200
    assert "cabinet-budget-2027" in changed.text

    old = await client.get("/en/article/cabinet-budget", follow_redirects=False)
    assert old.status_code == 301
    assert old.headers["location"] == "/en/article/cabinet-budget-2027"
    live = await client.get("/en/article/cabinet-budget-2027")
    assert live.status_code == 200
    assert "Cabinet approves the 2027 budget" in live.text

    taken = await client.post(
        f"/admin/stories/{localization_id}/slug",
        data={"csrf_token": _csrf(changed.text), "slug": "embargo-briefing"},
        follow_redirects=True,
    )
    assert "already in use" in taken.text
    assert 'value="cabinet-budget-2027"' in taken.text

    noted = await client.post(
        f"/admin/stories/{localization_id}/corrections",
        data={
            "csrf_token": _csrf(taken.text),
            "kind": "correction",
            "text": "The deficit figure was wrong.",
        },
        follow_redirects=True,
    )
    assert "The deficit figure was wrong." in noted.text
    published = await client.get("/en/article/cabinet-budget-2027")
    assert "Correction" in published.text
    assert "The deficit figure was wrong." in published.text

    client.cookies.clear()
    writer_csrf = await api_login(client, writer)
    denied_note = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/corrections",
        headers={"x-csrf-token": writer_csrf},
        json={"kind": "correction", "text": "Writer note"},
    )
    assert denied_note.status_code == 403
    denied_slug = await client.post(
        f"/api/v1/admin/localizations/{localization_id}/slug",
        headers={"x-csrf-token": writer_csrf},
        json={"slug": "writer-slug"},
    )
    assert denied_slug.status_code == 403
    desk = await client.get(f"/admin/stories/{localization_id}")
    assert f"/admin/stories/{localization_id}/slug" not in desk.text
    assert f"/admin/stories/{localization_id}/corrections" not in desk.text
