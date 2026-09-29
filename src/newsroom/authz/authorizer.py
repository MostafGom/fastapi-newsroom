import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from newsroom.authz.models import Role, UserRole
from newsroom.authz.permissions import Perm


@dataclass(frozen=True, slots=True)
class Grant:
    role_key: str
    rank: int
    section_id: uuid.UUID | None
    permissions: frozenset[str]

    @property
    def is_global(self) -> bool:
        return self.section_id is None


class Grants:
    """Resolved role grants for one user. Global grants cover every section."""

    def __init__(self, grants: Iterable[Grant] = ()) -> None:
        self._grants = tuple(grants)

    @property
    def items(self) -> tuple[Grant, ...]:
        return self._grants

    @property
    def max_rank(self) -> int:
        return max((g.rank for g in self._grants), default=0)

    @property
    def role_keys(self) -> frozenset[str]:
        return frozenset(g.role_key for g in self._grants)

    def all_permissions(self) -> frozenset[str]:
        return frozenset().union(*(g.permissions for g in self._grants))

    def has(self, perm: Perm, *, section_id: uuid.UUID | None = None) -> bool:
        """``section_id=None`` asks for a global grant; otherwise global or that section."""
        for grant in self._grants:
            if perm not in grant.permissions:
                continue
            if grant.is_global or (section_id is not None and grant.section_id == section_id):
                return True
        return False

    def has_anywhere(self, perm: Perm) -> bool:
        return any(perm in g.permissions for g in self._grants)

    def sections_with(self, perm: Perm) -> frozenset[uuid.UUID] | None:
        """Sections where ``perm`` applies; ``None`` means every section (a global grant)."""
        sections: set[uuid.UUID] = set()
        for grant in self._grants:
            if perm in grant.permissions:
                if grant.section_id is None:
                    return None
                sections.add(grant.section_id)
        return frozenset(sections)


class Authorizer(Protocol):
    async def grants_for(self, user_id: uuid.UUID) -> Grants: ...


class DbAuthorizer:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def grants_for(self, user_id: uuid.UUID) -> Grants:
        result = await self.db.execute(
            select(UserRole)
            .where(UserRole.user_id == user_id)
            .options(selectinload(UserRole.role).selectinload(Role.permissions))
        )
        return Grants(
            Grant(
                role_key=ur.role.key,
                rank=ur.role.rank,
                section_id=ur.section_id,
                permissions=frozenset(p.code for p in ur.role.permissions),
            )
            for ur in result.scalars().all()
        )
