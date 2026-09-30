from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

from newsroom.auth.dependencies import ensure_csrf_token
from newsroom.authz.permissions import Perm
from newsroom.core.config import get_settings
from newsroom.core.i18n import locale_info, translate

PACKAGE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

_MONTHS_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_MONTHS_AR = (
    "يناير",
    "فبراير",
    "مارس",
    "أبريل",
    "مايو",
    "يونيو",
    "يوليو",
    "أغسطس",
    "سبتمبر",
    "أكتوبر",
    "نوفمبر",
    "ديسمبر",
)


def _asset_version() -> str:
    css = STATIC_DIR / "dist" / "app.css"
    try:
        return str(int(css.stat().st_mtime))
    except OSError:
        return "0"


def format_date(value: datetime | date | None, locale: str) -> str:
    if value is None:
        return ""
    names = _MONTHS_AR if locale.split("-", 1)[0] == "ar" else _MONTHS_EN
    return f"{value.day} {names[value.month - 1]} {value.year}"


def _request_locale(request: Request) -> str:
    settings = get_settings()
    enabled = getattr(request.state, "enabled_locales", None) or settings.supported_locales
    default = getattr(request.state, "default_locale", None) or settings.default_locale
    locale = request.path_params.get("locale")
    if isinstance(locale, str) and locale in enabled:
        return locale
    principal = getattr(request.state, "principal", None)
    profile = getattr(principal.user, "staff_profile", None) if principal else None
    if profile is not None and profile.preferred_locale in enabled:
        return profile.preferred_locale
    return default


def _context(request: Request) -> dict[str, Any]:
    locale = _request_locale(request)
    settings = get_settings()
    directions = getattr(request.state, "locale_directions", None) or {}
    direction = directions.get(locale) or locale_info(locale).direction.value
    enabled = getattr(request.state, "enabled_locales", None) or settings.supported_locales
    return {
        "app_name": getattr(request.state, "site_name", None) or settings.app_name,
        "locale": locale,
        "direction": direction,
        "supported_locales": enabled,
        "locale_names": getattr(request.state, "locale_names", {}) or {},
        "registration_open": getattr(request.state, "registration_open", True),
        "nav_sections": getattr(request.state, "nav_sections", []),
        "edition_date": datetime.now(UTC).date(),
        "format_date": format_date,
        "csrf_token": ensure_csrf_token(request),
        "principal": getattr(request.state, "principal", None),
        "perms": Perm,
        "is_htmx": request.headers.get("hx-request") == "true",
        "asset_version": _asset_version(),
        "_": lambda key, **params: translate(locale, key, **params),
    }


templates = Jinja2Templates(directory=TEMPLATES_DIR, context_processors=[_context])
