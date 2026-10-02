import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newsroom.core.models import Base, Timestamps, UUIDPrimaryKey, pg_enum


class PageStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class Page(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "pages"

    key: Mapped[str] = mapped_column(String(64), unique=True)
    sort_order: Mapped[int] = mapped_column(default=0, server_default=text("0"))

    translations: Mapped[list[PageTranslation]] = relationship(
        back_populates="page", cascade="all, delete-orphan", lazy="selectin"
    )


class PageTranslation(UUIDPrimaryKey, Base):
    __tablename__ = "page_translations"
    __table_args__ = (
        UniqueConstraint("page_id", "locale"),
        UniqueConstraint("locale", "slug"),
    )

    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"))
    locale: Mapped[str] = mapped_column(ForeignKey("locales.code"))
    slug: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    body_html: Mapped[str] = mapped_column(Text)
    status: Mapped[PageStatus] = mapped_column(pg_enum(PageStatus, "page_status"))

    page: Mapped[Page] = relationship(back_populates="translations")
