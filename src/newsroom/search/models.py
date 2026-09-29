import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from newsroom.core.models import Base


class SearchDocument(Base):
    """One row per published localization. Drafts and takedowns are absent."""

    __tablename__ = "search_documents"
    __table_args__ = (
        Index("ix_search_documents_document", "document", postgresql_using="gin"),
        Index(
            "ix_search_documents_recent",
            "locale",
            "published_at",
            "localization_id",
        ),
    )

    localization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("article_localizations.id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(String(10))
    slug: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300))
    excerpt: Mapped[str | None] = mapped_column(String(1000))
    body_text: Mapped[str] = mapped_column(Text)
    section_id: Mapped[uuid.UUID]
    section_slug: Mapped[str] = mapped_column(String(160))
    section_name: Mapped[str] = mapped_column(String(120))
    tag_slugs: Mapped[list[str]] = mapped_column(ARRAY(String(160)))
    published_at: Mapped[datetime]
    document: Mapped[str] = mapped_column(TSVECTOR)
