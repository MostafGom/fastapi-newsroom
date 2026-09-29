import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newsroom.core.models import Base, Timestamps, UUIDPrimaryKey


class Section(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "sections"

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sections.id", ondelete="RESTRICT"), index=True
    )
    key: Mapped[str] = mapped_column(String(64), unique=True)
    sort_order: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))

    translations: Mapped[list[SectionTranslation]] = relationship(
        back_populates="section", cascade="all, delete-orphan", lazy="selectin"
    )


class SectionTranslation(UUIDPrimaryKey, Base):
    __tablename__ = "section_translations"
    __table_args__ = (
        UniqueConstraint("section_id", "locale"),
        UniqueConstraint("locale", "slug"),
    )

    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"))
    locale: Mapped[str] = mapped_column(ForeignKey("locales.code"))
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)

    section: Mapped[Section] = relationship(back_populates="translations")


class Tag(UUIDPrimaryKey, Base):
    __tablename__ = "tags"

    key: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    translations: Mapped[list[TagTranslation]] = relationship(
        back_populates="tag", cascade="all, delete-orphan", lazy="selectin"
    )


class TagTranslation(UUIDPrimaryKey, Base):
    __tablename__ = "tag_translations"
    __table_args__ = (
        UniqueConstraint("tag_id", "locale"),
        UniqueConstraint("locale", "slug"),
    )

    tag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"))
    locale: Mapped[str] = mapped_column(ForeignKey("locales.code"))
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(160))

    tag: Mapped[Tag] = relationship(back_populates="translations")
