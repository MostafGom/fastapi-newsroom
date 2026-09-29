import uuid
from datetime import date, datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from newsroom.core.models import Base, UUIDPrimaryKey


class NewsletterIssue(UUIDPrimaryKey, Base):
    __tablename__ = "newsletter_issues"
    __table_args__ = (UniqueConstraint("locale", "edition_date"),)

    locale: Mapped[str] = mapped_column(ForeignKey("locales.code"))
    edition_date: Mapped[date]
    subject: Mapped[str] = mapped_column(String(300))
    story_slugs: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class NewsletterDelivery(Base):
    __tablename__ = "newsletter_deliveries"

    issue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("newsletter_issues.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
