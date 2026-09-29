import uuid
from datetime import datetime

from sqlalchemy import Column, ForeignKey, String, Table, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newsroom.core.models import Base, UUIDPrimaryKey

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_code",
        ForeignKey("permissions.code", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Permission(Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str] = mapped_column(String(255))


class Role(UUIDPrimaryKey, Base):
    __tablename__ = "roles"

    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    rank: Mapped[int] = mapped_column(default=0, server_default=text("0"))

    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions, lazy="selectin"
    )


class UserRole(UUIDPrimaryKey, Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "section_id", postgresql_nulls_not_distinct=True),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"))
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sections.id", ondelete="CASCADE")
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    role: Mapped[Role] = relationship(lazy="joined", innerjoin=True)
