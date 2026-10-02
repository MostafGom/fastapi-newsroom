import json
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from pathlib import Path

from newsroom.core.config import Settings, get_settings

MESSAGES_DIR = Path(__file__).resolve().parent.parent / "messages"
UI_LOCALE_COOKIE = "nr_ui_locale"


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
    *,
    supported: list[str] | None = None,
    default: str | None = None,
) -> str:
    settings = settings or get_settings()
    codes = supported if supported is not None else settings.supported_locales
    fallback = default or settings.default_locale
    if requested and requested in codes:
        return requested
    for tag in parse_accept_language(accept_language or ""):
        if tag in codes:
            return tag
        base = tag.split("-", 1)[0]
        if base in codes:
            return base
    return fallback


def ordered_locales(codes: list[str], default: str) -> list[str]:
    """Default language first, then the remaining codes in their existing order."""
    if default in codes:
        return [default, *[code for code in codes if code != default]]
    return list(codes)


@cache
def catalog_codes() -> frozenset[str]:
    return frozenset(path.stem for path in MESSAGES_DIR.glob("*.json"))


def interface_locales(codes: list[str], default: str) -> list[str]:
    """Dashboard languages: enabled locales that have a message catalog, default first."""
    catalogs = catalog_codes()
    return [code for code in ordered_locales(codes, default) if code in catalogs]


@cache
def _catalog(code: str) -> dict[str, str]:
    path = MESSAGES_DIR / f"{code}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def translate(code: str, key: str, **params: object) -> str:
    text = _catalog(code).get(key) or _catalog(get_settings().default_locale).get(key) or key
    return text.format(**params) if params else text
