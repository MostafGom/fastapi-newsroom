import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from newsroom.core.models import Base


class HomepageSlot(Base):
    """One published localization pinned to a locale's front page, in order."""

    __tablename__ = "homepage_slots"
    __table_args__ = (UniqueConstraint("locale", "localization_id"),)

    locale: Mapped[str] = mapped_column(ForeignKey("locales.code"), primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    localization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("article_localizations.id", ondelete="CASCADE")
    )
    label: Mapped[str | None] = mapped_column(String(120))
