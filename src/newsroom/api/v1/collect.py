"""Public beacon. A bad token, a staff browser, or a full rate limit is ignored."""

import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

import structlog
from fastapi import APIRouter, Request, Response

from newsroom.analytics.classify import device_class, is_bot, referrer_class
from newsroom.analytics.ingest import EventBuffer
from newsroom.analytics.schemas import CollectIn
from newsroom.analytics.tokens import read_page_token
from newsroom.auth.dependencies import SettingsDep

log = structlog.get_logger("newsroom.analytics")

router = APIRouter(tags=["public"])


@router.post("/collect", status_code=204)
async def collect(request: Request, payload: CollectIn, settings: SettingsDep) -> Response:
    if request.cookies.get(settings.staff_session_cookie):
        return Response(status_code=204)
    visitor = _visitor(request.cookies.get(settings.visitor_cookie))
    if visitor is None:
        return Response(status_code=204)
    if is_bot(request.headers.get("user-agent")):
        return Response(status_code=204)
    claims = read_page_token(settings.secret_key.get_secret_value(), payload.token)
    if claims is None:
        return Response(status_code=204)
    if payload.type == "click" and not payload.click_target:
        return Response(status_code=204)
    buffer: EventBuffer | None = getattr(request.app.state, "analytics_buffer", None)
    if buffer is None:
        return Response(status_code=204)
    address = request.client.host if request.client else None
    if not buffer.allow(str(visitor), address):
        return Response(status_code=204)
    site_host = urlsplit(settings.public_base_url).hostname or ""
    try:
        await buffer.add(
            {
                "occurred_at": datetime.now(UTC),
                "type": payload.type,
                "view_id": payload.view_id,
                "localization_id": claims.localization_id,
                "article_id": claims.article_id,
                "section_id": claims.section_id,
                "page_id": claims.page_id,
                "locale": claims.locale,
                "surface": claims.surface,
                "visitor_id": visitor,
                "referrer_class": referrer_class(
                    request.headers.get("referer"),
                    request.url.hostname or "",
                    site_host,
                ),
                "device_class": device_class(request.headers.get("user-agent")),
                "engaged_ms": payload.engaged_ms,
                "scroll_pct": payload.scroll_pct,
                "click_target": payload.click_target if payload.type == "click" else None,
            }
        )
    except Exception:
        log.exception("analytics_ingest_failed")
    return Response(status_code=204)


def _visitor(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
