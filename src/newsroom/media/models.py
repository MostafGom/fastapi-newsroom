import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newsroom.core.models import Base, UUIDPrimaryKey
from newsroom.users.models import User


class MediaAsset(UUIDPrimaryKey, Base):
    __tablename__ = "media_assets"

    storage_key: Mapped[str] = mapped_column(String(200), unique=True)
    mime_type: Mapped[str] = mapped_column(String(80))
    width: Mapped[int | None]
    height: Mapped[int | None]
    byte_size: Mapped[int]
    filename: Mapped[str | None] = mapped_column(String(200))
    credit: Mapped[str | None] = mapped_column(String(200))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    translations: Mapped[list[MediaTranslation]] = relationship(
        back_populates="asset", cascade="all, delete-orphan", lazy="selectin"
    )
    uploader: Mapped[User] = relationship()


class MediaTranslation(Base):
    __tablename__ = "media_translations"

    media_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(ForeignKey("locales.code"), primary_key=True)
    caption: Mapped[str | None] = mapped_column(Text)
    alt_text: Mapped[str | None] = mapped_column(String(500))

    asset: Mapped[MediaAsset] = relationship(back_populates="translations")
