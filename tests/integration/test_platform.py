"""Cross-cutting behaviour: health, request IDs, error formats, contract stubs, migrations."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection

from newsroom.models import Base


async def test_health(client: AsyncClient) -> None:
    assert (await client.get("/healthz")).json() == {"status": "ok"}
    assert (await client.get("/readyz")).json() == {"status": "ok", "database": "ok"}


async def test_request_id_is_generated_and_propagated(client: AsyncClient) -> None:
    generated = await client.get("/healthz")
    assert len(generated.headers["x-request-id"]) == 32

    echoed = await client.get("/healthz", headers={"x-request-id": "trace-abc-12345"})
    assert echoed.headers["x-request-id"] == "trace-abc-12345"

    rejected = await client.get("/healthz", headers={"x-request-id": "bad id\n"})
    assert rejected.headers["x-request-id"] != "bad id\n"


async def test_api_errors_are_problem_json(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist", headers={"x-request-id": "req-12345678"})
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "not_found"
    assert body["request_id"] == "req-12345678"
    assert body["instance"] == "/api/v1/does-not-exist"


async def test_validation_errors_list_fields(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/login", json={"email": "not-an-email"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_failed"
    assert {tuple(e["loc"]) for e in body["errors"]} >= {("body", "email"), ("body", "password")}


async def test_html_errors_are_pages(client: AsyncClient) -> None:
    response = await client.get("/xx/")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")


async def test_public_locales_come_from_the_database(client: AsyncClient) -> None:
    locales = (await client.get("/api/v1/locales")).json()
    assert [(loc["code"], loc["direction"], loc["is_default"]) for loc in locales] == [
        ("ar", "rtl", True),
        ("en", "ltr", False),
    ]


async def test_public_article_list_is_live(client: AsyncClient) -> None:
    response = await client.get("/api/v1/articles")
    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_openapi_exposes_the_full_contract(client: AsyncClient) -> None:
    paths = (await client.get("/api/openapi.json")).json()["paths"]
    for path in (
        "/api/v1/articles/{slug}",
        "/api/v1/admin/localizations/{localization_id}/transitions",
        "/api/v1/admin/localizations/{localization_id}/revisions/{revision_id}/restore",
        "/api/v1/admin/users/{user_id}/roles",
        "/api/v1/admin/audit-events",
    ):
        assert path in paths
    assert not any(p.startswith("/admin") for p in paths), "HTML routes must stay out of OpenAPI"


async def test_models_and_migrations_do_not_drift(connection: AsyncConnection) -> None:
    def diff(sync_conn: object) -> list[object]:
        context = MigrationContext.configure(sync_conn, opts={"compare_type": True})  # type: ignore[arg-type]
        return compare_metadata(context, Base.metadata)

    assert await connection.run_sync(diff) == []


async def test_public_home_is_localized(client: AsyncClient) -> None:
    root = await client.get("/")
    assert root.status_code == 307
    assert root.headers["location"] == "/ar/"

    arabic = await client.get("/ar/")
    assert '<html lang="ar" dir="rtl">' in arabic.text
    assert arabic.text.index('href="/ar/"') < arabic.text.index('href="/en/"')
    assert "nr_csrf=" in arabic.headers.get("set-cookie", "")

    english = await client.get("/en/")
    assert '<html lang="en" dir="ltr">' in english.text
    assert "set-cookie" not in english.headers, "a valid CSRF cookie is reused, not rotated"


async def test_admin_language_switch(client: AsyncClient) -> None:
    login = await client.get("/admin/login")
    assert '<html lang="ar" dir="rtl">' in login.text
    arabic_link = 'href="/admin/language/ar?next='
    english_link = 'href="/admin/language/en?next='
    assert login.text.index(arabic_link) < login.text.index(english_link)
    assert login.text.index("العربية") < login.text.index(">English<")

    switched = await client.get("/admin/language/en", params={"next": "/admin/login"})
    assert switched.status_code == 303
    assert switched.headers["location"] == "/admin/login"
    cookie = next(
        item for item in switched.headers.get_list("set-cookie") if "nr_ui_locale=" in item
    )
    assert cookie.startswith("nr_ui_locale=en")
    assert "Path=/admin" in cookie

    english_desk = await client.get("/admin/login")
    assert '<html lang="en" dir="ltr">' in english_desk.text

    rejected = await client.get("/admin/language/fr", params={"next": "/admin/login"})
    assert rejected.status_code == 404

    outside = await client.get("/admin/language/en", params={"next": "https://evil.example/admin"})
    assert outside.status_code == 303
    assert outside.headers["location"] == "/admin/"

    public = await client.get("/ar/")
    assert '<html lang="ar" dir="rtl">' in public.text
