from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.locales.models import Locale


class LocaleRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_enabled(self) -> Sequence[Locale]:
        result = await self.db.execute(
            select(Locale).where(Locale.is_enabled).order_by(Locale.sort_order, Locale.code)
        )
        return result.scalars().all()

    async def get(self, code: str) -> Locale | None:
        return await self.db.get(Locale, code)
