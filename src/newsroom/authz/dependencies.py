from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends

from newsroom.auth.dependencies import OptionalStaff
from newsroom.auth.principal import Principal
from newsroom.authz.permissions import Perm
from newsroom.core.errors import NotAuthenticated, PermissionDenied


async def require_staff(principal: OptionalStaff) -> Principal:
    if principal is None:
        raise NotAuthenticated("Staff login required")
    return principal


CurrentStaff = Annotated[Principal, Depends(require_staff)]


def require_permission(perm: Perm) -> Callable[[Principal], Awaitable[Principal]]:
    """Coarse route guard: the principal holds ``perm`` in at least one scope.

    Section scope, ownership and state are enforced by services on the loaded entity.
    """

    async def dependency(principal: CurrentStaff) -> Principal:
        if not principal.grants.has_anywhere(perm):
            raise PermissionDenied(f"Missing permission: {perm.value}")
        return principal

    dependency.__name__ = f"require_{perm.name.lower()}"
    return dependency
