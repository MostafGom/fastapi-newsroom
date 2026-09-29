import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.authz.authorizer import DbAuthorizer
from newsroom.authz.models import Permission, Role
from newsroom.authz.permissions import SYSTEM_ROLES, Perm
from newsroom.authz.seed import seed_rbac
from newsroom.taxonomy.models import Section
from tests.conftest import MakeStaff, api_login

TAG = {"key": "x", "translations": [{"locale": "en", "name": "X", "slug": "x"}]}


@pytest.mark.parametrize(
    ("role", "path", "expected"),
    [
        ("writer", "/api/v1/admin/users", 403),
        ("editor", "/api/v1/admin/users", 403),
        ("admin", "/api/v1/admin/users", 200),
        ("writer", "/api/v1/admin/audit-events", 403),
        ("admin", "/api/v1/admin/audit-events", 200),
        (None, "/api/v1/admin/articles", 200),
    ],
)
async def test_route_guards(
    client: AsyncClient, make_staff: MakeStaff, role: str | None, path: str, expected: int
) -> None:
    await api_login(client, await make_staff(role))
    response = await client.get(path)
    assert response.status_code == expected, response.text
    if expected == 403:
        assert response.json()["code"] == "permission_denied"


async def test_writer_cannot_create_tags_but_editor_can(
    client: AsyncClient, make_staff: MakeStaff
) -> None:
    csrf = await api_login(client, await make_staff("writer"))
    denied = await client.post("/api/v1/admin/tags", json=TAG, headers={"x-csrf-token": csrf})
    assert denied.status_code == 403

    client.cookies.clear()
    csrf = await api_login(client, await make_staff("editor"))
    allowed = await client.post("/api/v1/admin/tags", json=TAG, headers={"x-csrf-token": csrf})
    assert allowed.status_code == 201


async def test_section_scoped_grants_resolve_from_the_database(
    db: AsyncSession, make_staff: MakeStaff
) -> None:
    politics = Section(key="politics")
    sports = Section(key="sports")
    db.add_all([politics, sports])
    await db.flush()

    account = await make_staff("editor", section_id=politics.id)
    grants = await DbAuthorizer(db).grants_for(account.id)  # type: ignore[arg-type]
    assert grants.has(Perm.ARTICLE_PUBLISH, section_id=politics.id)
    assert not grants.has(Perm.ARTICLE_PUBLISH, section_id=sports.id)
    assert not grants.has(Perm.ARTICLE_PUBLISH)


async def test_seed_is_idempotent_and_matches_code(db: AsyncSession) -> None:
    await seed_rbac(db)
    await seed_rbac(db)
    assert await db.scalar(select(func.count()).select_from(Permission)) == len(Perm)
    roles = {r.key: r for r in (await db.scalars(select(Role))).all()}
    for definition in SYSTEM_ROLES:
        role = roles[definition.key]
        assert role.is_system
        assert {p.code for p in role.permissions} == {p.value for p in definition.permissions}


async def test_seed_removes_stale_permissions(db: AsyncSession) -> None:
    db.add(Permission(code="legacy.thing", description="old"))
    await db.commit()
    result = await seed_rbac(db)
    assert result.removed_permissions == ["legacy.thing"]
    assert await db.get(Permission, "legacy.thing") is None
