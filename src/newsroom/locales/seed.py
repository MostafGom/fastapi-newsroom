from typing import Any

from sqlalchemy import CursorResult
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.core.i18n import TextDirection
from newsroom.locales.models import Locale

DEFAULT_LOCALES = (
    {
        "code": "ar",
        "name": "Arabic",
        "native_name": "العربية",
        "direction": TextDirection.RTL,
        "is_default": True,
        "sort_order": 0,
    },
    {
        "code": "en",
        "name": "English",
        "native_name": "English",
        "direction": TextDirection.LTR,
        "is_default": False,
        "sort_order": 1,
    },
)


async def seed_locales(db: AsyncSession) -> int:
    """Insert launch locales if missing. Never overwrites edits made through the dashboard."""
    result: CursorResult[Any] = await db.execute(  # type: ignore[assignment]
        insert(Locale)
        .values(list(DEFAULT_LOCALES))
        .on_conflict_do_nothing(index_elements=[Locale.code])
    )
    await db.commit()
    return result.rowcount or 0
