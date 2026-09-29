from sqlalchemy import String, text
from sqlalchemy.orm import Mapped, mapped_column

from newsroom.core.models import Base


class SiteSettings(Base):
    """One row. Secrets stay in the environment."""

    __tablename__ = "site_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    site_name: Mapped[str] = mapped_column(String(120))
    registration_enabled: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
