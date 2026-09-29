import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from newsroom.core.models import Base, UUIDPrimaryKey
from newsroom.users.models import User


class Comment(UUIDPrimaryKey, Base):
    __tablename__ = "comments"
    __table_args__ = (Index("ix_comments_localization_created", "localization_id", "created_at"),)

    localization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("article_localizations.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    hidden_at: Mapped[datetime | None]

    user: Mapped[User] = relationship(lazy="selectin")
