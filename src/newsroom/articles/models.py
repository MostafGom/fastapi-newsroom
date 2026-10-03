import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newsroom.articles.schemas import ArticleType, RevisionKind
from newsroom.articles.workflow import ArticleStatus, CorrectionKind
from newsroom.core.models import Base, Timestamps, UUIDPrimaryKey, pg_enum
from newsroom.taxonomy.models import Section, Tag
from newsroom.users.models import User


class AuthorKind(StrEnum):
    STAFF = "staff"
    CONTRIBUTOR = "contributor"
    AGENCY = "agency"


class Author(UUIDPrimaryKey, Base):
    __tablename__ = "authors"

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), unique=True)
    kind: Mapped[AuthorKind] = mapped_column(pg_enum(AuthorKind, "author_kind"))
    key: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    translations: Mapped[list[AuthorTranslation]] = relationship(
        back_populates="author", cascade="all, delete-orphan", lazy="selectin"
    )
    user: Mapped[User | None] = relationship()


class AuthorTranslation(UUIDPrimaryKey, Base):
    __tablename__ = "author_translations"
    __table_args__ = (
        UniqueConstraint("author_id", "locale"),
        UniqueConstraint("locale", "slug"),
    )

    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("authors.id", ondelete="CASCADE"))
    locale: Mapped[str] = mapped_column(ForeignKey("locales.code"))
    display_name: Mapped[str] = mapped_column(String(120))
    bio: Mapped[str | None] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(String(160))

    author: Mapped[Author] = relationship(back_populates="translations")


class Article(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "articles"

    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sections.id"), index=True)
    article_type: Mapped[ArticleType] = mapped_column(pg_enum(ArticleType, "article_type"))
    lead_media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    is_breaking: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    section: Mapped[Section] = relationship(lazy="selectin")
    localizations: Mapped[list[ArticleLocalization]] = relationship(
        back_populates="article", lazy="selectin"
    )
    article_authors: Mapped[list[ArticleAuthor]] = relationship(
        back_populates="article", cascade="all, delete-orphan", lazy="selectin"
    )
    article_tags: Mapped[list[ArticleTag]] = relationship(
        back_populates="article", cascade="all, delete-orphan", lazy="selectin"
    )


class ArticleAuthor(Base):
    __tablename__ = "article_authors"

    article_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("authors.id", ondelete="RESTRICT"), primary_key=True
    )
    position: Mapped[int] = mapped_column(default=0, server_default=text("0"))

    article: Mapped[Article] = relationship(back_populates="article_authors")
    author: Mapped[Author] = relationship(lazy="selectin")


class ArticleTag(Base):
    __tablename__ = "article_tags"

    article_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )

    article: Mapped[Article] = relationship(back_populates="article_tags")
    tag: Mapped[Tag] = relationship(lazy="selectin")


class ArticleLocalization(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "article_localizations"
    __table_args__ = (
        UniqueConstraint("article_id", "locale"),
        UniqueConstraint("locale", "slug"),
        CheckConstraint(
            "deleted_at IS NULL OR first_published_at IS NULL",
            name="deleted_never_published",
        ),
        Index(
            "ix_article_localizations_scheduled",
            "publish_at",
            postgresql_where=text("status = 'scheduled'"),
        ),
        Index(
            "ix_article_localizations_public",
            "locale",
            "published_at",
            postgresql_where=text("status = 'published'"),
        ),
    )

    article_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("articles.id", ondelete="RESTRICT"), index=True
    )
    locale: Mapped[str] = mapped_column(ForeignKey("locales.code"))
    slug: Mapped[str] = mapped_column(String(200))
    status: Mapped[ArticleStatus] = mapped_column(
        pg_enum(ArticleStatus, "article_status"), default=ArticleStatus.DRAFT
    )
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("article_revisions.id", use_alter=True, name="fk_localizations_current_revision")
    )
    published_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "article_revisions.id", use_alter=True, name="fk_localizations_published_revision"
        )
    )
    publish_at: Mapped[datetime | None]
    unpublish_at: Mapped[datetime | None]
    published_at: Mapped[datetime | None]
    first_published_at: Mapped[datetime | None]
    update_requested_at: Mapped[datetime | None]
    lock_version: Mapped[int] = mapped_column(default=1, server_default=text("1"))
    legal_hold: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    deleted_at: Mapped[datetime | None]

    article: Mapped[Article] = relationship(back_populates="localizations", lazy="selectin")
    revisions: Mapped[list[ArticleRevision]] = relationship(
        back_populates="localization",
        foreign_keys="ArticleRevision.localization_id",
        lazy="selectin",
    )
    corrections: Mapped[list[Correction]] = relationship(
        back_populates="localization", lazy="selectin"
    )


class ArticleRevision(UUIDPrimaryKey, Base):
    __tablename__ = "article_revisions"
    __table_args__ = (UniqueConstraint("localization_id", "revision_no"),)

    localization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("article_localizations.id", ondelete="RESTRICT"), index=True
    )
    revision_no: Mapped[int]
    parent_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("article_revisions.id", use_alter=True, name="fk_revisions_parent")
    )
    restored_from_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("article_revisions.id", use_alter=True, name="fk_revisions_restored_from")
    )
    kind: Mapped[RevisionKind] = mapped_column(pg_enum(RevisionKind, "revision_kind"))
    title: Mapped[str] = mapped_column(String(300))
    subtitle: Mapped[str | None] = mapped_column(String(500))
    excerpt: Mapped[str | None] = mapped_column(String(1000))
    body: Mapped[dict[str, Any]] = mapped_column(JSONB)
    body_html: Mapped[str] = mapped_column(Text)
    seo_title: Mapped[str | None] = mapped_column(String(300))
    seo_description: Mapped[str | None] = mapped_column(String(500))
    change_note: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    localization: Mapped[ArticleLocalization] = relationship(
        back_populates="revisions", foreign_keys=[localization_id]
    )


class SlugRedirect(Base):
    __tablename__ = "slug_redirects"

    locale: Mapped[str] = mapped_column(ForeignKey("locales.code"), primary_key=True)
    old_slug: Mapped[str] = mapped_column(String(200), primary_key=True)
    localization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("article_localizations.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Correction(UUIDPrimaryKey, Base):
    __tablename__ = "corrections"

    localization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("article_localizations.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[CorrectionKind] = mapped_column(pg_enum(CorrectionKind, "correction_kind"))
    text: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    localization: Mapped[ArticleLocalization] = relationship(back_populates="corrections")


class Bookmark(Base):
    __tablename__ = "bookmarks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    article: Mapped[Article] = relationship(lazy="selectin")
