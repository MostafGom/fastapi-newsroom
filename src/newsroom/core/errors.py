from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from newsroom.core.context import request_id_var

log = structlog.get_logger(__name__)

PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    """Base for domain errors. Services raise these; handlers map them to HTTP."""

    status_code: int = 400
    code: str = "bad_request"
    title: str | None = None

    def __init__(self, detail: str | None = None, *, extra: dict[str, Any] | None = None) -> None:
        self.detail = detail
        self.extra = extra or {}
        super().__init__(detail or self.code)


class NotAuthenticated(AppError):
    status_code = 401
    code = "not_authenticated"


class PermissionDenied(AppError):
    status_code = 403
    code = "permission_denied"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class Gone(AppError):
    status_code = 410
    code = "gone"


class CsrfFailed(AppError):
    status_code = 403
    code = "csrf_failed"


class NotImplementedYet(AppError):
    status_code = 501
    code = "not_implemented"


def is_api_request(request: Request) -> bool:
    return request.url.path.startswith("/api/")


def problem(
    request: Request,
    status: int,
    *,
    code: str,
    title: str | None = None,
    detail: str | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title or HTTPStatus(status).phrase,
        "status": status,
        "code": code,
        "instance": request.url.path,
        "request_id": request_id_var.get(),
    }
    if detail:
        body["detail"] = detail
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def _html_error(request: Request, status: int, detail: str | None) -> Response:
    if status == 401 and request.url.path.startswith("/admin"):
        login_url = f"/admin/login?next={quote(request.url.path)}"
        if request.headers.get("hx-request") == "true":
            return Response(status_code=401, headers={"HX-Redirect": login_url})
        return RedirectResponse(login_url, status_code=303)
    templates = getattr(request.app.state, "templates", None)
    if templates is None:
        return HTMLResponse(f"<h1>{status}</h1>", status_code=status)
    return templates.TemplateResponse(
        request,
        "errors/error.html",
        {"status": status, "title": HTTPStatus(status).phrase, "detail": detail},
        status_code=status,
    )


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> Response:
        if is_api_request(request):
            return problem(
                request,
                exc.status_code,
                code=exc.code,
                title=exc.title,
                detail=exc.detail,
                extra=exc.extra,
            )
        return _html_error(request, exc.status_code, exc.detail)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> Response:
        detail = exc.detail if isinstance(exc.detail, str) else None
        if is_api_request(request):
            code = HTTPStatus(exc.status_code).name.lower()
            response = problem(request, exc.status_code, code=code, detail=detail)
        else:
            response = _html_error(request, exc.status_code, detail)
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> Response:
        errors = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        if is_api_request(request):
            return problem(
                request,
                422,
                code="validation_failed",
                detail="Request validation failed",
                extra={"errors": errors},
            )
        return _html_error(request, 422, "Invalid input")

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> Response:
        log.exception("unhandled_exception", path=request.url.path)
        if is_api_request(request):
            return problem(request, 500, code="internal_error")
        return _html_error(request, 500, None)
