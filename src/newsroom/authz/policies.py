"""Rules a role table cannot express: rank, ownership, and self-protection."""

from newsroom.authz.authorizer import Grants
from newsroom.core.errors import PermissionDenied


def ensure_outranks(actor: Grants, target: Grants) -> None:
    """An actor may only manage users whose highest rank is strictly below their own."""
    if actor.max_rank <= target.max_rank:
        raise PermissionDenied("You cannot manage a user at or above your own rank")


def ensure_can_grant_role(actor: Grants, role_rank: int) -> None:
    if actor.max_rank <= role_rank:
        raise PermissionDenied("You cannot grant a role at or above your own rank")
