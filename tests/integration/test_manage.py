import re

from httpx import AsyncClient

from tests.conftest import MakeStaff, StaffAccount

CSRF_FIELD = re.compile(r'name="csrf_token" value="([^"]+)"')
SECTION_FORM = re.compile(r'action="/admin/sections/([0-9a-f-]{36})"')
GRANT_FORM = re.compile(r"/roles/([0-9a-f-]{36})/revoke")


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


async def test_management_screens_follow_the_role(
    client: AsyncClient, make_staff: MakeStaff
) -> None:
    writer = await make_staff("writer")
    editor = await make_staff("editor")
    admin = await make_staff("admin")

    await _login(client, writer)
    home = await client.get("/admin/")
    assert home.status_code == 200
    assert "/admin/sections" not in home.text
    assert "/admin/users" not in home.text
    denied = await client.get("/admin/sections")
    assert denied.status_code == 403

    await _login(client, editor)
    tags = await client.get("/admin/tags")
    assert tags.status_code == 200
    assert "الوسوم" in tags.text
    created_tag = await client.post(
        "/admin/tags",
        data={
            "csrf_token": _csrf(tags.text),
            "key": "budget-tag",
            "name_en": "Budget",
            "slug_en": "budget-tag",
            "name_ar": "موازنة",
            "slug_ar": "muwazana-tag",
        },
        follow_redirects=True,
    )
    assert created_tag.status_code == 200
    assert "Budget" in created_tag.text
    by_name = await client.get("/admin/tags", params={"q": "موازنة"})
    assert "budget-tag" in by_name.text
    by_key = await client.get("/admin/tags", params={"q": "BUDGET-TAG"})
    assert "budget-tag" in by_key.text
    missed_tag = await client.get("/admin/tags", params={"q": "%"})
    assert "budget-tag" not in missed_tag.text
    assert "لا شيء يطابق." in missed_tag.text
    authors = await client.get("/admin/authors")
    created_author = await client.post(
        "/admin/authors",
        data={
            "csrf_token": _csrf(authors.text),
            "kind": "contributor",
            "key": "wire-guest",
            "name_en": "Wire Guest",
            "slug_en": "wire-guest",
            "name_ar": "ضيف الوكالة",
            "slug_ar": "wire-guest-ar",
        },
        follow_redirects=True,
    )
    assert "wire-guest" in created_author.text
    by_byline = await client.get("/admin/authors", params={"q": "ضيف"})
    assert "wire-guest" in by_byline.text
    missed_author = await client.get("/admin/authors", params={"q": "zzz-nomatch"})
    assert "wire-guest" not in missed_author.text
    assert "لا شيء يطابق." in missed_author.text
    assert (await client.get("/admin/users")).status_code == 403
    assert (await client.get("/admin/sections")).status_code == 403

    await _login(client, admin)
    desk = await client.get("/admin/")
    assert "/admin/sections" in desk.text
    assert "/admin/audit" in desk.text

    sections = await client.get("/admin/sections")
    assert sections.status_code == 200
    created_section = await client.post(
        "/admin/sections",
        data={
            "csrf_token": _csrf(sections.text),
            "key": "citydesk",
            "sort_order": "2",
            "name_en": "City",
            "slug_en": "city",
            "name_ar": "المدينة",
            "slug_ar": "city-ar",
        },
        follow_redirects=True,
    )
    assert "City" in created_section.text
    section_id = SECTION_FORM.search(created_section.text)
    assert section_id is not None
    updated = await client.post(
        f"/admin/sections/{section_id.group(1)}",
        data={
            "csrf_token": _csrf(created_section.text),
            "sort_order": "4",
            "is_active": "1",
            "name_en": "City desk",
            "slug_en": "city",
            "name_ar": "المدينة",
            "slug_ar": "city-ar",
        },
        follow_redirects=True,
    )
    assert "City desk" in updated.text
    by_section = await client.get("/admin/sections", params={"q": "المدينة"})
    assert "citydesk" in by_section.text
    missed_section = await client.get("/admin/sections", params={"q": "zzz-nomatch"})
    assert "citydesk" not in missed_section.text
    assert "لا شيء يطابق." in missed_section.text

    users = await client.get("/admin/users")
    hired = await client.post(
        "/admin/users",
        data={
            "csrf_token": _csrf(users.text),
            "email": "desk-hire@example.com",
            "display_name": "Desk Hire",
            "password": "desk-password-1",
        },
        follow_redirects=False,
    )
    assert hired.status_code == 303
    user_path = hired.headers["location"].split("?")[0]
    account = await client.get(hired.headers["location"])
    assert account.status_code == 200
    assert "desk-hire@example.com" in account.text
    assert "تم الحفظ." in account.text
    granted = await client.post(
        f"{user_path}/roles",
        data={"csrf_token": _csrf(account.text), "role_key": "writer", "section_id": ""},
        follow_redirects=True,
    )
    assert "مُنح الدور." in granted.text
    assert "writer" in granted.text
    grant = GRANT_FORM.search(granted.text)
    assert grant is not None
    suspended = await client.post(
        user_path,
        data={
            "csrf_token": _csrf(granted.text),
            "display_name": "Desk Hire",
            "status": "suspended",
        },
        follow_redirects=True,
    )
    assert "موقوف" in suspended.text

    revoked = await client.post(
        f"{user_path}/roles/{grant.group(1)}/revoke",
        data={"csrf_token": _csrf(suspended.text)},
        follow_redirects=True,
    )
    assert "سُحب الدور." in revoked.text
    assert f"/roles/{grant.group(1)}/revoke" not in revoked.text

    audit = await client.get("/admin/audit?action=user.role_granted")
    assert audit.status_code == 200
    assert "user.role_granted" in audit.text

    listed = await client.get("/api/v1/admin/audit-events?limit=1")
    assert listed.status_code == 200
    body = listed.json()
    assert body["next_cursor"]
    follow = await client.get(f"/api/v1/admin/audit-events?limit=1&cursor={body['next_cursor']}")
    assert follow.status_code == 200
    assert follow.json()["items"][0]["id"] != body["items"][0]["id"]
    filtered = await client.get("/api/v1/admin/audit-events?action=user.role_granted")
    assert filtered.json()["items"]
    assert all(item["action"] == "user.role_granted" for item in filtered.json()["items"])
