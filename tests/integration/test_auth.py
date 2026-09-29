import re
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.audit.models import AuditEvent
from newsroom.auth.models import AuthSession
from newsroom.auth.service import AuthService, utcnow
from newsroom.core.config import Settings
from newsroom.users.models import User, UserStatus
from tests.conftest import MakeStaff, api_login

CSRF_FIELD = re.compile(r'name="csrf_token" value="([^"]+)"')


async def test_staff_api_login_me_logout(client: AsyncClient, make_staff: MakeStaff) -> None:
    account = await make_staff("editor")
    csrf = await api_login(client, account)
    assert client.cookies.get("nr_staff")

    me = (await client.get("/api/v1/auth/me")).json()
    assert me["email"] == account.email
    assert me["roles"] == [{"role": "editor", "section_id": None}]
    assert "article.publish" in me["permissions"]

    assert (await client.post("/api/v1/auth/logout")).status_code == 403, "CSRF required"
    logout = await client.post("/api/v1/auth/logout", headers={"x-csrf-token": csrf})
    assert logout.status_code == 204
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_revoked_session_stops_working_immediately(
    client: AsyncClient, make_staff: MakeStaff, db: AsyncSession
) -> None:
    account = await make_staff("admin")
    await api_login(client, account)
    session = await db.scalar(select(AuthSession).where(AuthSession.user_id == account.id))
    assert session is not None
    session.revoked_at = utcnow()
    await db.commit()
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_suspended_user_is_locked_out(
    client: AsyncClient, make_staff: MakeStaff, db: AsyncSession
) -> None:
    account = await make_staff("admin")
    await api_login(client, account)
    user = await db.get(User, account.id)
    assert user is not None
    user.status = UserStatus.SUSPENDED
    await db.commit()
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_wrong_password_and_wrong_audience_look_identical(
    client: AsyncClient, make_staff: MakeStaff, db: AsyncSession
) -> None:
    account = await make_staff("writer")
    wrong_password = await client.post(
        "/api/v1/auth/login",
        json={"email": account.email, "password": "nope", "audience": "staff"},
    )
    wrong_audience = await client.post(
        "/api/v1/auth/login",
        json={"email": account.email, "password": account.password, "audience": "reader"},
    )
    unknown = await client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@example.com", "password": "x", "audience": "staff"},
    )
    for response in (wrong_password, wrong_audience, unknown):
        assert response.status_code == 401
        assert response.json()["code"] == "invalid_credentials"

    failures = await db.scalars(
        select(AuditEvent).where(
            AuditEvent.action == "auth.login_failed", AuditEvent.actor_id == account.id
        )
    )
    assert len(failures.all()) == 2


async def test_login_is_audited_with_session_and_request_id(
    client: AsyncClient, make_staff: MakeStaff, db: AsyncSession
) -> None:
    account = await make_staff("editor")
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": account.email, "password": account.password, "audience": "staff"},
        headers={"x-request-id": "login-req-0001"},
    )
    assert response.status_code == 200
    event = await db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "auth.login", AuditEvent.actor_id == account.id
        )
    )
    assert event is not None
    assert event.request_id == "login-req-0001"
    assert event.after is not None
    assert event.after["session_id"] != "None"


async def test_bearer_token_skips_csrf(
    client: AsyncClient, make_staff: MakeStaff, db: AsyncSession, settings: Settings
) -> None:
    account = await make_staff("admin")
    user = await db.get(User, account.id)
    assert user is not None
    issued = await AuthService(db, settings).create_api_token(user, "ci", timedelta(days=1))
    headers = {"authorization": f"Bearer {issued.token}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    stub = await client.post(
        "/api/v1/admin/tags",
        headers=headers,
        json={"key": "x", "translations": [{"locale": "en", "name": "X", "slug": "x"}]},
    )
    assert stub.status_code == 201


async def test_staff_token_in_reader_cookie_is_ignored(
    client: AsyncClient, make_staff: MakeStaff
) -> None:
    account = await make_staff("super_admin")
    await api_login(client, account)
    token = client.cookies["nr_staff"]
    client.cookies.clear()
    client.cookies.set("nr_session", token)
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_admin_html_login_flow(client: AsyncClient, make_staff: MakeStaff) -> None:
    account = await make_staff("editor")

    anonymous = await client.get("/admin/")
    assert anonymous.status_code == 303
    assert anonymous.headers["location"] == "/admin/login?next=/admin/"

    form = await client.get("/admin/login")
    match = CSRF_FIELD.search(form.text)
    assert match is not None
    csrf = match.group(1)

    missing_csrf = await client.post(
        "/admin/login", data={"email": account.email, "password": account.password}
    )
    assert missing_csrf.status_code == 403

    bad_password = await client.post(
        "/admin/login", data={"csrf_token": csrf, "email": account.email, "password": "nope"}
    )
    assert bad_password.status_code == 401
    assert 'role="alert"' in bad_password.text

    ok = await client.post(
        "/admin/login",
        data={
            "csrf_token": csrf,
            "email": account.email,
            "password": account.password,
            "next": "https://evil.example/admin",
        },
    )
    assert ok.status_code == 303
    assert ok.headers["location"] == "/admin/"

    dashboard = await client.get("/admin/")
    assert dashboard.status_code == 200
    assert "editor" in dashboard.text


async def test_htmx_requests_get_hx_redirect(client: AsyncClient) -> None:
    response = await client.get("/admin/", headers={"hx-request": "true"})
    assert response.status_code == 401
    assert response.headers["hx-redirect"].startswith("/admin/login")
