import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.audit.service import record_event
from newsroom.auth.models import AuthSession, SessionKind
from newsroom.auth.repository import SessionRepository
from newsroom.auth.schemas import Audience
from newsroom.core.config import Settings
from newsroom.core.errors import NotAuthenticated
from newsroom.core.security import hash_token, new_token, verify_password
from newsroom.users.models import User, UserKind
from newsroom.users.repository import UserRepository

log = structlog.get_logger(__name__)

AUDIENCE_KIND = {Audience.READER: UserKind.READER, Audience.STAFF: UserKind.STAFF}
AUDIENCE_SESSION = {Audience.READER: SessionKind.READER_WEB, Audience.STAFF: SessionKind.STAFF_WEB}


class InvalidCredentials(NotAuthenticated):
    code = "invalid_credentials"


@dataclass(frozen=True, slots=True)
class IssuedSession:
    token: str
    session: AuthSession


def utcnow() -> datetime:
    return datetime.now(UTC)


class AuthService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.users = UserRepository(db)
        self.sessions = SessionRepository(db)

    def _ttl(self, kind: SessionKind) -> timedelta:
        if kind is SessionKind.STAFF_WEB:
            return timedelta(hours=self.settings.staff_session_ttl_hours)
        return timedelta(hours=self.settings.reader_session_ttl_hours)

    async def login(
        self,
        email: str,
        password: str,
        audience: Audience,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> IssuedSession:
        user = await self.users.get_by_email(email)
        valid, upgraded_hash = verify_password(password, user.password_hash if user else None)
        if user is None or not valid or user.kind is not AUDIENCE_KIND[audience]:
            if user is not None and user.kind is UserKind.STAFF:
                record_event(
                    self.db,
                    actor_id=user.id,
                    action="auth.login_failed",
                    entity_type="user",
                    entity_id=user.id,
                )
                await self.db.commit()
            raise InvalidCredentials("Invalid email or password")
        if not user.is_active:
            raise InvalidCredentials("Account is not active")

        if upgraded_hash:
            user.password_hash = upgraded_hash
        now = utcnow()
        user.last_login_at = now
        issued = self._issue(user, AUDIENCE_SESSION[audience], now, ip=ip, user_agent=user_agent)
        if user.kind is UserKind.STAFF:
            record_event(
                self.db,
                actor_id=user.id,
                action="auth.login",
                entity_type="user",
                entity_id=user.id,
                after={"session_id": str(issued.session.id)},
            )
        await self.db.commit()
        log.info("login", user_id=str(user.id), audience=audience.value)
        return issued

    def _issue(
        self,
        user: User,
        kind: SessionKind,
        now: datetime,
        *,
        ip: str | None,
        user_agent: str | None,
        ttl: timedelta | None = None,
        name: str | None = None,
    ) -> IssuedSession:
        token = new_token()
        session = AuthSession(
            id=uuid.uuid7(),
            user=user,
            token_hash=hash_token(token),
            kind=kind,
            name=name,
            created_at=now,
            last_seen_at=now,
            expires_at=now + (ttl or self._ttl(kind)),
            ip=ip,
            user_agent=(user_agent or "")[:512] or None,
        )
        self.sessions.add(session)
        return IssuedSession(token=token, session=session)

    async def create_api_token(self, user: User, name: str, ttl: timedelta) -> IssuedSession:
        issued = self._issue(
            user, SessionKind.API_TOKEN, utcnow(), ip=None, user_agent=None, ttl=ttl, name=name
        )
        record_event(
            self.db,
            actor_id=user.id,
            action="auth.api_token_created",
            entity_type="user",
            entity_id=user.id,
            after={"name": name},
        )
        await self.db.commit()
        return issued

    async def resolve(self, token: str, allowed: frozenset[SessionKind]) -> AuthSession | None:
        """Return a live session for ``token`` of an allowed kind, sliding its expiry."""
        session = await self.sessions.get_by_token_hash(hash_token(token))
        now = utcnow()
        if (
            session is None
            or session.kind not in allowed
            or session.revoked_at is not None
            or session.expires_at <= now
            or not session.user.is_active
        ):
            return None
        touch_after = timedelta(seconds=self.settings.session_touch_interval_seconds)
        if now - session.last_seen_at >= touch_after:
            session.last_seen_at = now
            if session.kind is not SessionKind.API_TOKEN:
                session.expires_at = now + self._ttl(session.kind)
            await self.db.commit()
        return session

    async def logout(self, session: AuthSession) -> None:
        session.revoked_at = utcnow()
        if session.user.kind is UserKind.STAFF:
            record_event(
                self.db,
                actor_id=session.user_id,
                action="auth.logout",
                entity_type="user",
                entity_id=session.user_id,
            )
        await self.db.commit()
