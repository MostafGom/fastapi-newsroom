"""Rules a role table cannot express: rank, ownership, and self-protection."""

import uuid
from collections.abc import Iterable

from newsroom.authz.authorizer import Grants
from newsroom.authz.permissions import Perm
from newsroom.core.errors import PermissionDenied


def ensure_outranks(actor: Grants, target: Grants) -> None:
    """An actor may only manage users whose highest rank is strictly below their own."""
    if actor.max_rank <= target.max_rank:
        raise PermissionDenied("You cannot manage a user at or above your own rank")


def ensure_can_grant_role(actor: Grants, role_rank: int) -> None:
    if actor.max_rank <= role_rank:
        raise PermissionDenied("You cannot grant a role at or above your own rank")


def ensure_can_assign(
    actor: Grants,
    *,
    role_rank: int,
    role_permissions: Iterable[str],
    section_id: uuid.UUID | None,
) -> None:
    """Grant or revoke a role only where you assign roles, and only with powers you hold there.

    A grant with no section covers the whole newsroom, so it needs a global role.assign.
    """
    if not actor.has(Perm.ROLE_ASSIGN, section_id=section_id):
        where = "across the newsroom" if section_id is None else "in that section"
        raise PermissionDenied(f"You cannot assign roles {where}")
    ensure_can_grant_role(actor, role_rank)
    missing = sorted(set(role_permissions) - actor.permissions_in(section_id))
    if missing:
        raise PermissionDenied(
            f"That role carries permissions you do not hold: {', '.join(missing)}"
        )
