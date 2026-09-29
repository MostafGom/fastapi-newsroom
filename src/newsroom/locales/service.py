"""Enabled languages are rows. Adding one does not require a migration."""

import re

from pydantic import Field
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.audit.service import record_event
from newsroom.auth.principal import Principal
from newsroom.authz.permissions import Perm
from newsroom.core.errors import Conflict, NotFound, PermissionDenied
from newsroom.core.i18n import TextDirection
from newsroom.core.schemas import Schema
from newsroom.locales.models import Locale
from newsroom.locales.repository import LocaleRepository

_CODE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,4})?$")


class LocaleCreate(Schema):
    code: str = Field(max_length=10)
    name: str = Field(min_length=1, max_length=64)
    native_name: str = Field(min_length=1, max_length=64)
    direction: TextDirection
    sort_order: int = 0


class LocaleAdminOut(Schema):
    code: str
    name: str
    native_name: str
    direction: TextDirection
    is_default: bool
    is_enabled: bool
    sort_order: int


class LocaleService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.locales = LocaleRepository(db)

    async def list_all(self) -> list[LocaleAdminOut]:
        from sqlalchemy import select

        rows = (
            await self.db.scalars(select(Locale).order_by(Locale.sort_order, Locale.code))
        ).all()
        return [_out(row) for row in rows]

    async def create(self, actor: Principal, payload: LocaleCreate) -> LocaleAdminOut:
        self._require(actor)
        code = payload.code.strip().lower()
        if _CODE.fullmatch(code) is None:
            raise Conflict("Locale code must look like ar or zh-hant")
        row = Locale(
            code=code,
            name=payload.name.strip(),
            native_name=payload.native_name.strip(),
            direction=payload.direction,
            is_default=False,
            is_enabled=True,
            sort_order=payload.sort_order,
        )
        self.db.add(row)
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="locale.created",
            entity_type="locale",
            entity_id=code,
            after={"name": row.name, "direction": row.direction.value},
        )
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise Conflict("That locale already exists") from exc
        return _out(row)

    async def set_enabled(self, actor: Principal, code: str, enabled: bool) -> LocaleAdminOut:
        self._require(actor)
        row = await self.locales.get(code)
        if row is None:
            raise NotFound("Locale not found")
        if not enabled and row.is_default:
            raise Conflict("Set another default language before disabling this one")
        if not enabled and row.is_enabled:
            enabled_count = len(await self.locales.list_enabled())
            if enabled_count <= 1:
                raise Conflict("At least one language must stay enabled")
        row.is_enabled = enabled
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="locale.updated",
            entity_type="locale",
            entity_id=row.code,
            after={"is_enabled": enabled},
        )
        await self.db.commit()
        return _out(row)

    async def set_default(self, actor: Principal, code: str) -> LocaleAdminOut:
        self._require(actor)
        row = await self.locales.get(code)
        if row is None:
            raise NotFound("Locale not found")
        await self.db.execute(
            update(Locale).where(Locale.is_default.is_(True)).values(is_default=False)
        )
        await self.db.flush()
        row.is_default = True
        row.is_enabled = True
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="locale.updated",
            entity_type="locale",
            entity_id=row.code,
            after={"is_default": True},
        )
        await self.db.commit()
        return _out(row)

    @staticmethod
    def _require(actor: Principal) -> None:
        if not actor.grants.has_anywhere(Perm.LOCALE_MANAGE):
            raise PermissionDenied("Missing permission: locale.manage")


def _out(row: Locale) -> LocaleAdminOut:
    return LocaleAdminOut(
        code=row.code,
        name=row.name,
        native_name=row.native_name,
        direction=row.direction,
        is_default=row.is_default,
        is_enabled=row.is_enabled,
        sort_order=row.sort_order,
    )
