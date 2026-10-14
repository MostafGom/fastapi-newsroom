import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.authz.models import Permission, Role, UserRole
from newsroom.authz.permissions import Perm
from newsroom.taxonomy.models import Section
from tests.conftest import MakeStaff, api_login


async def _sections(db: AsyncSession) -> tuple[Section, Section]:
    politics = Section(key="grant-politics")
    sports = Section(key="grant-sports")
    db.add_all([politics, sports])
    await db.flush()
    return politics, sports


async def _role(db: AsyncSession, key: str, rank: int, perms: list[Perm]) -> None:
    rows = (
        await db.scalars(select(Permission).where(Permission.code.in_([p.value for p in perms])))
    ).all()
    db.add(Role(key=key, name=key, rank=rank, is_system=False, permissions=list(rows)))
    await db.flush()


async def test_a_section_admin_grants_roles_only_in_their_own_section(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    politics, sports = await _sections(db)
    section_admin = await make_staff("admin", section_id=politics.id)
    target = await make_staff()
    headers = {"X-CSRF-Token": await api_login(client, section_admin)}

    async def grant(user_id: object, role: str, section: object) -> int:
        response = await client.post(
            f"/api/v1/admin/users/{user_id}/roles",
            json={"role_key": role, "section_id": str(section) if section else None},
            headers=headers,
        )
        return response.status_code

    assert await grant(section_admin.id, "editor", None) == 403
    assert await grant(target.id, "editor", None) == 403
    assert await grant(target.id, "editor", sports.id) == 403
    assert await grant(target.id, "editor", uuid.uuid4()) == 404
    assert await grant(target.id, "editor", politics.id) == 201


async def test_a_role_cannot_carry_permissions_the_granter_lacks(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    await _role(db, "night_desk", 25, [Perm.ARTICLE_READ, Perm.ARTICLE_PURGE])
    await _role(db, "night_reader", 25, [Perm.ARTICLE_READ])
    admin = await make_staff("admin")
    target = await make_staff()
    headers = {"X-CSRF-Token": await api_login(client, admin)}

    denied = await client.post(
        f"/api/v1/admin/users/{target.id}/roles", json={"role_key": "night_desk"}, headers=headers
    )
    assert denied.status_code == 403
    assert "article.purge" in denied.json()["detail"]
    allowed = await client.post(
        f"/api/v1/admin/users/{target.id}/roles", json={"role_key": "night_reader"}, headers=headers
    )
    assert allowed.status_code == 201, allowed.text


async def test_a_section_admin_cannot_revoke_a_newsroom_wide_grant(
    client: AsyncClient, db: AsyncSession, make_staff: MakeStaff
) -> None:
    politics, _ = await _sections(db)
    section_admin = await make_staff("admin", section_id=politics.id)
    target = await make_staff("writer")
    grant_id = await db.scalar(select(UserRole.id).where(UserRole.user_id == target.id))
    headers = {"X-CSRF-Token": await api_login(client, section_admin)}

    revoked = await client.delete(
        f"/api/v1/admin/users/{target.id}/roles/{grant_id}", headers=headers
    )
    assert revoked.status_code == 403
    assert await db.get(UserRole, grant_id) is not None
