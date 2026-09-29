from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.core.db import get_db
from newsroom.core.i18n import negotiate_locale
from newsroom.core.site import load_site_context


async def resolve_api_locale(request: Request, db: Annotated[AsyncSession, Depends(get_db)]) -> str:
    await load_site_context(request, db)
    return negotiate_locale(
        request.query_params.get("locale"),
        request.headers.get("accept-language"),
        supported=list(request.state.enabled_locales),
        default=request.state.default_locale,
    )
