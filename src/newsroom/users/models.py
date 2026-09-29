import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newsroom.core.models import Base, Timestamps, UUIDPrimaryKey, pg_enum


class UserKind(StrEnum):
    READER = "reader"
    STAFF = "staff"


class UserStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_kind_status", "kind", "status"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    kind: Mapped[UserKind] = mapped_column(pg_enum(UserKind, "user_kind"))
    status: Mapped[UserStatus] = mapped_column(
        pg_enum(UserStatus, "user_status"), default=UserStatus.ACTIVE
    )
    email_verified_at: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]

    staff_profile: Mapped[StaffProfile | None] = relationship(
        back_populates="user", uselist=False, lazy="selectin", cascade="all, delete-orphan"
    )
    reader_profile: Mapped[ReaderProfile | None] = relationship(
        back_populates="user", uselist=False, lazy="selectin", cascade="all, delete-orphan"
    )

    @property
    def display_name(self) -> str | None:
        if self.staff_profile is not None:
            return self.staff_profile.display_name
        if self.reader_profile is not None:
            return self.reader_profile.display_name
        return None

    @property
    def is_active(self) -> bool:
        return self.status is UserStatus.ACTIVE


class StaffProfile(Base):
    __tablename__ = "staff_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    display_name: Mapped[str] = mapped_column(String(120))
    job_title: Mapped[str | None] = mapped_column(String(120))
    bio: Mapped[str | None] = mapped_column(Text)
    preferred_locale: Mapped[str | None] = mapped_column(ForeignKey("locales.code"))

    user: Mapped[User] = relationship(back_populates="staff_profile")


class ReaderProfile(Base):
    __tablename__ = "reader_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    display_name: Mapped[str | None] = mapped_column(String(120))
    preferred_locale: Mapped[str | None] = mapped_column(ForeignKey("locales.code"))
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    newsletter_opt_in: Mapped[bool] = mapped_column(default=False, server_default=text("false"))

    user: Mapped[User] = relationship(back_populates="reader_profile")
