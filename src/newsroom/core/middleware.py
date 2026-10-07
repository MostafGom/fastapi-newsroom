import re
import time
import uuid

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from newsroom.core.config import Settings
from newsroom.core.context import client_ip_var, request_id_var

log = structlog.get_logger("newsroom.access")

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestContextMiddleware:
    """Assigns a request ID, binds it to logs, and emits one access log line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid7().hex
        client = scope.get("client")
        request_id_var.set(request_id)
        client_ip_var.set(client[0] if client else None)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        status_code = 500
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["x-request-id"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            log.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )


class VisitorCookieMiddleware:
    """Gives each public browser a random id. The beacon sends it back; it is not a user id."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in {"GET", "HEAD"}:
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        existing = _cookie(scope, self.settings.visitor_cookie)
        mint = _is_public_document(path) and not _valid_uuid(existing)

        async def send_wrapper(message: Message) -> None:
            if mint and message["type"] == "http.response.start" and message["status"] < 400:
                secure = "; Secure" if self.settings.cookie_secure else ""
                max_age = self.settings.visitor_cookie_days * 24 * 60 * 60
                visitor = uuid.uuid4()
                MutableHeaders(scope=message).append(
                    "set-cookie",
                    f"{self.settings.visitor_cookie}={visitor}; Path=/; Max-Age={max_age}; "
                    f"HttpOnly; SameSite=Lax{secure}",
                )
            await send(message)

        await self.app(scope, receive, send_wrapper)


def _is_public_document(path: str) -> bool:
    return not path.startswith(("/admin", "/api", "/static", "/media", "/healthz", "/readyz"))


def _cookie(scope: Scope, name: str) -> str | None:
    raw = dict(scope.get("headers") or []).get(b"cookie", b"").decode("latin-1")
    for part in raw.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name and value:
            return value
    return None


def _valid_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


class CsrfCookieMiddleware:
    """Persists a CSRF token minted during the request (``request.state.new_csrf_token``)."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Request.state lives in this dict; create it here so copies of the scope share it.
        state = scope.setdefault("state", {})

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                token = state.get("new_csrf_token")
                if token:
                    secure = "; Secure" if self.settings.cookie_secure else ""
                    MutableHeaders(scope=message).append(
                        "set-cookie",
                        f"{self.settings.csrf_cookie}={token}; Path=/; SameSite=Lax{secure}",
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)
