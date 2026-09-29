import json
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from pathlib import Path

from fastapi import Request

from newsroom.core.config import Settings, get_settings

MESSAGES_DIR = Path(__file__).resolve().parent.parent / "messages"


class TextDirection(StrEnum):
    LTR = "ltr"
    RTL = "rtl"


RTL_LANGUAGES = frozenset({"ar", "fa", "he", "ur"})


@dataclass(frozen=True, slots=True)
class LocaleInfo:
    code: str
    direction: TextDirection


def locale_info(code: str) -> LocaleInfo:
    base = code.split("-", 1)[0].lower()
    direction = TextDirection.RTL if base in RTL_LANGUAGES else TextDirection.LTR
    return LocaleInfo(code=code, direction=direction)


def parse_accept_language(header: str) -> list[str]:
    """Return language tags ordered by quality, highest first."""
    weighted: list[tuple[float, int, str]] = []
    for index, part in enumerate(header.split(",")):
        piece = part.strip()
        if not piece:
            continue
        tag, _, params = piece.partition(";")
        quality = 1.0
        if params.strip().startswith("q="):
            try:
                quality = float(params.strip()[2:])
            except ValueError:
                quality = 0.0
        if quality > 0:
            weighted.append((-quality, index, tag.strip().lower()))
    return [tag for _, _, tag in sorted(weighted)]


def negotiate_locale(
    requested: str | None,
    accept_language: str | None,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    supported = settings.supported_locales
    if requested and requested in supported:
        return requested
    for tag in parse_accept_language(accept_language or ""):
        if tag in supported:
            return tag
        base = tag.split("-", 1)[0]
        if base in supported:
            return base
    return settings.default_locale


def resolve_api_locale(request: Request) -> str:
    return negotiate_locale(
        request.query_params.get("locale"), request.headers.get("accept-language")
    )


@cache
def _catalog(code: str) -> dict[str, str]:
    path = MESSAGES_DIR / f"{code}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def translate(code: str, key: str, **params: object) -> str:
    text = _catalog(code).get(key) or _catalog(get_settings().default_locale).get(key) or key
    return text.format(**params) if params else text
