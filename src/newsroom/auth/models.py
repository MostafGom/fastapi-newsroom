import uuid
from datetime import datetime
from enum import StrEnum
from ipaddress import IPv4Address, IPv6Address

from sqlalchemy import ForeignKey, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newsroom.core.models import Base, UUIDPrimaryKey, pg_enum
from newsroom.users.models import User


class SessionKind(StrEnum):
    READER_WEB = "reader_web"
    STAFF_WEB = "staff_web"
    API_TOKEN = "api_token"  # noqa: S105


class AuthSession(UUIDPrimaryKey, Base):
    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    kind: Mapped[SessionKind] = mapped_column(pg_enum(SessionKind, "session_kind"))
    name: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(index=True)
    revoked_at: Mapped[datetime | None]
    ip: Mapped[IPv4Address | IPv6Address | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(512))

    user: Mapped[User] = relationship(lazy="joined", innerjoin=True)
