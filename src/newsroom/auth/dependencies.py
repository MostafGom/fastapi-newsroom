import hmac
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Request, Response

from newsroom.auth.models import SessionKind
from newsroom.auth.principal import Principal
from newsroom.auth.schemas import Audience
from newsroom.auth.service import AuthService
from newsroom.authz.authorizer import DbAuthorizer
from newsroom.core.config import Settings, get_settings
from newsroom.core.db import DbSession
from newsroom.core.errors import CsrfFailed, NotAuthenticated
from newsroom.core.security import csrf_token_is_valid, new_csrf_token
from newsroom.users.models import UserKind

SettingsDep = Annotated[Settings, Depends(get_settings)]

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
CSRF_HEADER = "x-csrf-token"
CSRF_FIELD = "csrf_token"

STAFF_SESSION_KINDS = frozenset({SessionKind.STAFF_WEB, SessionKind.API_TOKEN})
READER_SESSION_KINDS = frozenset({SessionKind.READER_WEB, SessionKind.API_TOKEN})


def bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() or None if scheme.lower() == "bearer" else None


def session_cookie_name(settings: Settings, audience: Audience) -> str:
    if audience is Audience.STAFF:
        return settings.staff_session_cookie
    return settings.reader_session_cookie


async def _resolve(
    request: Request, db: DbSession, settings: Settings, audience: Audience
) -> Principal | None:
    token = bearer_token(request) or request.cookies.get(session_cookie_name(settings, audience))
    if not token:
        return None
    is_staff = audience is Audience.STAFF
    allowed = STAFF_SESSION_KINDS if is_staff else READER_SESSION_KINDS
    session = await AuthService(db, settings).resolve(token, allowed)
    if session is None:
        return None
    if session.user.kind is not (UserKind.STAFF if is_staff else UserKind.READER):
        return None
    principal = Principal(user=session.user, session=session)
    if is_staff:
        principal.grants = await DbAuthorizer(db).grants_for(session.user_id)
    request.state.principal = principal
    return principal


async def optional_staff(
    request: Request, db: DbSession, settings: SettingsDep
) -> Principal | None:
    return await _resolve(request, db, settings, Audience.STAFF)


async def optional_reader(
    request: Request, db: DbSession, settings: SettingsDep
) -> Principal | None:
    return await _resolve(request, db, settings, Audience.READER)


OptionalStaff = Annotated[Principal | None, Depends(optional_staff)]
OptionalReader = Annotated[Principal | None, Depends(optional_reader)]


async def require_reader(principal: OptionalReader) -> Principal:
    if principal is None:
        raise NotAuthenticated("Reader login required")
    return principal


CurrentReader = Annotated[Principal, Depends(require_reader)]


# ---- Cookies --------------------------------------------------------------------------------


def set_session_cookie(
    response: Response, settings: Settings, audience: Audience, token: str, expires: datetime
) -> None:
    response.set_cookie(
        session_cookie_name(settings, audience),
        token,
        expires=expires,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict" if audience is Audience.STAFF else "lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings, audience: Audience) -> None:
    response.delete_cookie(session_cookie_name(settings, audience), path="/")


# ---- CSRF (signed double-submit) ------------------------------------------------------------


def ensure_csrf_token(request: Request) -> str:
    """Return the request's CSRF token, minting one (set by middleware) if missing or invalid."""
    settings = get_settings()
    pending = getattr(request.state, "new_csrf_token", None)
    if pending:
        return pending
    existing = request.cookies.get(settings.csrf_cookie)
    if existing and csrf_token_is_valid(settings.secret_key.get_secret_value(), existing):
        return existing
    token = new_csrf_token(settings.secret_key.get_secret_value())
    request.state.new_csrf_token = token
    return token


async def _verify_csrf(request: Request, settings: Settings) -> None:
    cookie = request.cookies.get(settings.csrf_cookie)
    submitted = request.headers.get(CSRF_HEADER)
    if submitted is None and request.headers.get("content-type", "").startswith(
        ("application/x-www-form-urlencoded", "multipart/form-data")
    ):
        value = (await request.form()).get(CSRF_FIELD)
        submitted = value if isinstance(value, str) else None
    if not (
        cookie
        and submitted
        and hmac.compare_digest(cookie, submitted)
        and csrf_token_is_valid(settings.secret_key.get_secret_value(), cookie)
    ):
        raise CsrfFailed("Missing or invalid CSRF token")


async def csrf_protect(request: Request, settings: SettingsDep) -> None:
    """API variant: only cookie-authenticated unsafe requests need a token."""
    if request.method in SAFE_METHODS or bearer_token(request):
        return
    has_session_cookie = any(
        request.cookies.get(name)
        for name in (settings.reader_session_cookie, settings.staff_session_cookie)
    )
    if has_session_cookie:
        await _verify_csrf(request, settings)


async def csrf_protect_web(request: Request, settings: SettingsDep) -> None:
    """HTML variant: every unsafe request needs a token, including anonymous login forms."""
    if request.method not in SAFE_METHODS:
        await _verify_csrf(request, settings)
