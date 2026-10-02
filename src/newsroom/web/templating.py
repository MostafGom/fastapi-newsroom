from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Request
from fastapi.templating import Jinja2Templates
from hijridate import Gregorian

from newsroom.auth.dependencies import ensure_csrf_token
from newsroom.authz.permissions import Perm
from newsroom.core.config import get_settings
from newsroom.core.i18n import (
    UI_LOCALE_COOKIE,
    interface_locales,
    locale_info,
    ordered_locales,
    translate,
)

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
_HIJRI_MONTHS_EN = (
    "Muharram",
    "Safar",
    "Rabi al-Awwal",
    "Rabi al-Thani",
    "Jumada al-Ula",
    "Jumada al-Thani",
    "Rajab",
    "Shaban",
    "Ramadan",
    "Shawwal",
    "Dhu al-Qidah",
    "Dhu al-Hijjah",
)
_HIJRI_MONTHS_AR = (
    "محرم",
    "صفر",
    "ربيع الأول",
    "ربيع الآخر",
    "جمادى الأولى",
    "جمادى الآخرة",
    "رجب",
    "شعبان",
    "رمضان",
    "شوال",
    "ذو القعدة",
    "ذو الحجة",
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


def format_hijri(value: datetime | date | None, locale: str) -> str:
    """Umm al-Qura date for the same civil day as ``format_date``."""
    if value is None:
        return ""
    hijri = Gregorian(value.year, value.month, value.day).to_hijri()
    names = _HIJRI_MONTHS_AR if locale.split("-", 1)[0] == "ar" else _HIJRI_MONTHS_EN
    return f"{hijri.day} {names[hijri.month - 1]} {hijri.year}"


def _enabled_locales(request: Request) -> list[str]:
    settings = get_settings()
    enabled = getattr(request.state, "enabled_locales", None) or settings.supported_locales
    return list(enabled)


def _default_locale(request: Request) -> str:
    settings = get_settings()
    return getattr(request.state, "default_locale", None) or settings.default_locale


def _request_locale(request: Request) -> str:
    enabled = _enabled_locales(request)
    default = _default_locale(request)
    locale = request.path_params.get("locale")
    if isinstance(locale, str) and locale in enabled:
        return locale
    chosen = request.cookies.get(UI_LOCALE_COOKIE)
    if isinstance(chosen, str) and chosen in interface_locales(enabled, default):
        return chosen
    return default


def admin_return_path(request: Request) -> str:
    """Page to reopen after the dashboard language changes."""
    path = request.url.path
    if not path.startswith("/admin") or path.startswith("/admin/language"):
        return "/admin/"
    query = request.url.query
    return f"{path}?{query}" if query else path


def _context(request: Request) -> dict[str, Any]:
    locale = _request_locale(request)
    settings = get_settings()
    directions = getattr(request.state, "locale_directions", None) or {}
    direction = directions.get(locale) or locale_info(locale).direction.value
    enabled = _enabled_locales(request)
    default = _default_locale(request)
    return {
        "app_name": getattr(request.state, "site_name", None) or settings.app_name,
        "locale": locale,
        "direction": direction,
        "supported_locales": ordered_locales(enabled, default),
        "interface_locales": interface_locales(enabled, default),
        "admin_next": quote(admin_return_path(request), safe=""),
        "locale_names": getattr(request.state, "locale_names", {}) or {},
        "registration_open": getattr(request.state, "registration_open", True),
        "nav_sections": getattr(request.state, "nav_sections", []),
        "site_pages": getattr(request.state, "site_pages", []),
        "edition_date": datetime.now(UTC).date(),
        "format_date": format_date,
        "format_hijri": format_hijri,
        "csrf_token": ensure_csrf_token(request),
        "principal": getattr(request.state, "principal", None),
        "perms": Perm,
        "is_htmx": request.headers.get("hx-request") == "true",
        "asset_version": _asset_version(),
        "_": lambda key, **params: translate(locale, key, **params),
    }


templates = Jinja2Templates(directory=TEMPLATES_DIR, context_processors=[_context])
