"""HMAC page tokens. The browser sends the token back; it never chooses the story id."""

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass

from newsroom.analytics.models import SURFACES

_MAX_AGE = 60 * 60 * 24


@dataclass(frozen=True, slots=True)
class PageClaims:
    surface: str
    locale: str
    localization_id: uuid.UUID | None = None
    article_id: uuid.UUID | None = None
    section_id: uuid.UUID | None = None
    page_id: uuid.UUID | None = None
    tag_id: uuid.UUID | None = None


def issue_page_token(
    secret: str, claims: PageClaims, *, ttl_seconds: int, now: int | None = None
) -> str:
    if claims.surface not in SURFACES:
        raise ValueError("unknown surface")
    issued = int(time.time()) if now is None else now
    payload = {
        "art": _s(claims.article_id),
        "exp": issued + ttl_seconds,
        "loc": _s(claims.localization_id),
        "locl": claims.locale,
        "pg": _s(claims.page_id),
        "sec": _s(claims.section_id),
        "sur": claims.surface,
        "tag": _s(claims.tag_id),
    }
    body = _encode(payload)
    return f"{body}.{_sign(secret, body)}"


def read_page_token(secret: str, token: str, *, now: int | None = None) -> PageClaims | None:
    body, separator, signature = token.partition(".")
    if not separator or not body or not signature:
        return None
    if not hmac.compare_digest(signature, _sign(secret, body)):
        return None
    try:
        payload = json.loads(_decode(body))
    except ValueError, json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    surface = payload.get("sur")
    locale = payload.get("locl")
    if not isinstance(exp, int) or not isinstance(surface, str) or not isinstance(locale, str):
        return None
    moment = int(time.time()) if now is None else now
    if exp < moment or exp > moment + _MAX_AGE:
        return None
    if surface not in SURFACES or not locale or len(locale) > 10:
        return None
    try:
        return PageClaims(
            surface=surface,
            locale=locale,
            localization_id=_uuid(payload.get("loc")),
            article_id=_uuid(payload.get("art")),
            section_id=_uuid(payload.get("sec")),
            page_id=_uuid(payload.get("pg")),
            tag_id=_uuid(payload.get("tag")),
        )
    except ValueError:
        return None


def _s(value: uuid.UUID | None) -> str:
    return "" if value is None else str(value)


def _uuid(value: object) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("not a uuid")
    return uuid.UUID(value)


def _encode(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(body: str) -> bytes:
    padding = "=" * (-len(body) % 4)
    return base64.urlsafe_b64decode(body + padding)


def _sign(secret: str, body: str) -> str:
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
