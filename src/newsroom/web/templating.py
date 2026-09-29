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
        "csrf_token": ensure_csrf_token(request),
        "principal": getattr(request.state, "principal", None),
        "perms": Perm,
        "is_htmx": request.headers.get("hx-request") == "true",
        "_": lambda key, **params: translate(locale, key, **params),
    }


templates = Jinja2Templates(directory=TEMPLATES_DIR, context_processors=[_context])
