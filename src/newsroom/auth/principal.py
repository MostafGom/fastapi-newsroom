from dataclasses import dataclass, field

from newsroom.auth.models import AuthSession, SessionKind
from newsroom.authz.authorizer import Grants
from newsroom.users.models import User, UserKind


@dataclass(slots=True)
class Principal:
    user: User
    session: AuthSession
    grants: Grants = field(default_factory=Grants)

    @property
    def is_staff(self) -> bool:
        return self.user.kind is UserKind.STAFF

    @property
    def via_api_token(self) -> bool:
        return self.session.kind is SessionKind.API_TOKEN
