"""Request-scoped site name, open registration, and the enabled language list."""

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.core.config import get_settings
from newsroom.locales.models import Locale
from newsroom.settings.models import SiteSettings
from newsroom.settings.service import SINGLETON


async def load_site_context(request: Request, db: AsyncSession) -> None:
    """Read the language list and site row on this session so a test savepoint is visible."""
    if getattr(request.state, "site_ready", False):
        return
    settings = get_settings()
    rows = (
        await db.scalars(
            select(Locale).where(Locale.is_enabled).order_by(Locale.sort_order, Locale.code)
        )
    ).all()
    if rows:
        request.state.enabled_locales = [row.code for row in rows]
        request.state.locale_names = {row.code: row.native_name for row in rows}
        request.state.locale_directions = {row.code: row.direction.value for row in rows}
        request.state.default_locale = next(
            (row.code for row in rows if row.is_default), rows[0].code
        )
    else:
        request.state.enabled_locales = list(settings.supported_locales)
        request.state.locale_names = {}
        request.state.locale_directions = {}
        request.state.default_locale = settings.default_locale
    stored = await db.get(SiteSettings, SINGLETON)
    request.state.site_name = stored.site_name if stored is not None else settings.app_name
    request.state.registration_open = True if stored is None else stored.registration_enabled
    request.state.site_ready = True
