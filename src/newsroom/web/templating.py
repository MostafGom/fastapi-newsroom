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
    locale = request.path_params.get("locale")
    if isinstance(locale, str) and locale in settings.supported_locales:
        return locale
    principal = getattr(request.state, "principal", None)
    profile = getattr(principal.user, "staff_profile", None) if principal else None
    if profile is not None and profile.preferred_locale:
        return profile.preferred_locale
    return settings.default_locale


def _context(request: Request) -> dict[str, Any]:
    locale = _request_locale(request)
    info = locale_info(locale)
    settings = get_settings()
    return {
        "app_name": settings.app_name,
        "locale": locale,
        "direction": info.direction.value,
        "supported_locales": settings.supported_locales,
        "csrf_token": ensure_csrf_token(request),
        "principal": getattr(request.state, "principal", None),
        "perms": Perm,
        "is_htmx": request.headers.get("hx-request") == "true",
        "_": lambda key, **params: translate(locale, key, **params),
    }


templates = Jinja2Templates(directory=TEMPLATES_DIR, context_processors=[_context])
