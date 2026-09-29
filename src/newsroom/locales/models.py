from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from newsroom.core.i18n import TextDirection
from newsroom.core.models import Base, pg_enum


class Locale(Base):
    __tablename__ = "locales"
    __table_args__ = (
        Index(
            "uq_locales_single_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    native_name: Mapped[str] = mapped_column(String(64))
    direction: Mapped[TextDirection] = mapped_column(pg_enum(TextDirection, "text_direction"))
    is_default: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    is_enabled: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(default=0, server_default=text("0"))
