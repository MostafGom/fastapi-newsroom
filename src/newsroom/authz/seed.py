from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.authz.models import Permission, Role
from newsroom.authz.permissions import PERMISSION_DESCRIPTIONS, SYSTEM_ROLES, Perm


@dataclass(frozen=True, slots=True)
class SeedResult:
    permissions: int
    roles: int
    removed_permissions: list[str]


async def seed_rbac(db: AsyncSession) -> SeedResult:
    """Make permissions and system roles match code. Idempotent; custom roles are untouched."""
    codes = [p.value for p in Perm]
    stmt = insert(Permission).values(
        [{"code": code, "description": PERMISSION_DESCRIPTIONS[Perm(code)]} for code in codes]
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[Permission.code], set_={"description": stmt.excluded.description}
        )
    )
    stale = (await db.scalars(select(Permission.code).where(Permission.code.not_in(codes)))).all()
    if stale:
        await db.execute(delete(Permission).where(Permission.code.in_(stale)))

    permissions = {p.code: p for p in (await db.scalars(select(Permission))).all()}
    existing = {r.key: r for r in (await db.scalars(select(Role))).all()}
    for definition in SYSTEM_ROLES:
        role = existing.get(definition.key) or Role(key=definition.key)
        role.name = definition.name
        role.description = definition.description
        role.rank = definition.rank
        role.is_system = True
        role.permissions = [permissions[p.value] for p in sorted(definition.permissions)]
        db.add(role)

    await db.commit()
    return SeedResult(
        permissions=len(codes), roles=len(SYSTEM_ROLES), removed_permissions=list(stale)
    )
