import re

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.audit.models import AuditEvent
from newsroom.seed.demo import DEMO_PASSWORD, seed_demo
from tests.conftest import StaffAccount, api_login

CSRF_FIELD = re.compile(r'name="csrf_token" value="([^"]+)"')
DOC = {
    "type": "doc",
    "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "How to reach the desk."}]}
    ],
}


def _csrf(html: str) -> str:
    match = CSRF_FIELD.search(html)
    assert match is not None
    return match.group(1)


async def test_site_pages_publish_and_stay_off_the_home(
    client: AsyncClient, db: AsyncSession
) -> None:
    await seed_demo(db)
    editor = StaffAccount(id=None, email="demo-editor@example.com", password=DEMO_PASSWORD)
    admin = StaffAccount(id=None, email="demo-super@example.com", password=DEMO_PASSWORD)

    editor_token = await api_login(client, editor)
    denied = await client.post(
        "/api/v1/admin/pages",
        json={"key": "fixture-page", "sort_order": 1},
        headers={"X-CSRF-Token": editor_token},
    )
    assert denied.status_code == 403

    client.cookies.clear()
    token = await api_login(client, admin)
    headers = {"X-CSRF-Token": token}
    missing = await client.post(
        "/api/v1/admin/pages", json={"key": "fixture-page", "sort_order": 1}
    )
    assert missing.status_code == 403

    created = await client.post(
        "/api/v1/admin/pages",
        json={"key": "fixture-page", "sort_order": 1},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    page_id = created.json()["id"]
    translation = {
        "locale": "en",
        "title": "Fixture",
        "slug": "fixture-page",
        "body": DOC,
        "status": "draft",
    }
    draft = await client.put(
        f"/api/v1/admin/pages/{page_id}/translations",
        json=translation,
        headers=headers,
    )
    assert draft.status_code == 200, draft.text
    hidden = await client.get("/en/page/fixture-page")
    assert hidden.status_code == 404

    published = await client.put(
        f"/api/v1/admin/pages/{page_id}/translations",
        json={**translation, "status": "published"},
        headers=headers,
    )
    assert published.status_code == 200, published.text
    shown = await client.get("/en/page/fixture-page")
    assert shown.status_code == 200
    assert "How to reach the desk." in shown.text
    assert 'href="/en/page/fixture-page"' in shown.text

    home = await client.get("/en/")
    assert "Cabinet approves the 2027 budget" in home.text
    assert 'href="/en/page/about"' in home.text
    assert "About" in home.text

    other = await client.post(
        "/api/v1/admin/pages",
        json={"key": "fixture-other", "sort_order": 2},
        headers=headers,
    )
    assert other.status_code == 201, other.text
    conflict = await client.put(
        f"/api/v1/admin/pages/{other.json()['id']}/translations",
        json={**translation, "title": "Other", "status": "published"},
        headers=headers,
    )
    assert conflict.status_code == 409

    recorded = await db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "page.published",
            AuditEvent.entity_id == page_id,
        )
    )
    assert recorded is not None
    assert recorded.entity_id == page_id

    removed = await client.delete(f"/api/v1/admin/pages/{page_id}", headers=headers)
    assert removed.status_code == 204
    assert (await client.get("/en/page/fixture-page")).status_code == 404

    client.cookies.clear()
    form = await client.get("/admin/login")
    signed_in = await client.post(
        "/admin/login",
        data={
            "csrf_token": _csrf(form.text),
            "email": admin.email,
            "password": admin.password,
        },
    )
    assert signed_in.status_code == 303
    blocked = await client.post("/admin/pages", data={"key": "desk-page", "sort_order": "0"})
    assert blocked.status_code == 403
    desk = await client.get("/admin/pages")
    saved = await client.post(
        "/admin/pages",
        data={"csrf_token": _csrf(desk.text), "key": "desk-page", "sort_order": "3"},
    )
    assert saved.status_code == 303
    assert saved.headers["location"].startswith("/admin/pages/")
