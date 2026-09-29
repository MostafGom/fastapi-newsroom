from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.audit.service import record_event
from newsroom.auth.principal import Principal
from newsroom.authz.permissions import Perm
from newsroom.core.config import get_settings
from newsroom.core.errors import PermissionDenied
from newsroom.core.schemas import Schema
from newsroom.settings.models import SiteSettings

SINGLETON = 1


class SiteSettingsOut(Schema):
    site_name: str
    registration_enabled: bool


class SiteSettingsUpdate(Schema):
    site_name: str = Field(min_length=1, max_length=120)
    registration_enabled: bool


class SettingsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self) -> SiteSettingsOut:
        row = await self._row()
        return SiteSettingsOut(
            site_name=row.site_name, registration_enabled=row.registration_enabled
        )

    async def update(self, actor: Principal, payload: SiteSettingsUpdate) -> SiteSettingsOut:
        if not actor.grants.has_anywhere(Perm.SETTINGS_MANAGE):
            raise PermissionDenied("Missing permission: settings.manage")
        row = await self._row()
        row.site_name = payload.site_name.strip()
        row.registration_enabled = payload.registration_enabled
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="settings.updated",
            entity_type="site_settings",
            entity_id=str(SINGLETON),
            after=payload.model_dump(),
        )
        await self.db.commit()
        return SiteSettingsOut(
            site_name=row.site_name, registration_enabled=row.registration_enabled
        )

    async def _row(self) -> SiteSettings:
        row = await self.db.get(SiteSettings, SINGLETON)
        if row is not None:
            return row
        row = SiteSettings(
            id=SINGLETON,
            site_name=get_settings().app_name,
            registration_enabled=True,
        )
        self.db.add(row)
        await self.db.flush()
        return row
