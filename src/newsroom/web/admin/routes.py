import json
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from newsroom.articles.body import InvalidBody, render_body
from newsroom.articles.workflow import TRANSITIONS, ArticleStatus
from newsroom.auth.dependencies import (
    OptionalStaff,
    SettingsDep,
    clear_session_cookie,
    csrf_protect_web,
    set_session_cookie,
)
from newsroom.auth.schemas import Audience
from newsroom.auth.service import AuthService, InvalidCredentials
from newsroom.authz.dependencies import CurrentStaff
from newsroom.core.db import DbSession
from newsroom.core.i18n import UI_LOCALE_COOKIE, interface_locales
from newsroom.web.templating import templates

router = APIRouter(
    prefix="/admin", dependencies=[Depends(csrf_protect_web)], include_in_schema=False
)


def safe_next(target: str | None) -> str:
    """Only allow same-site relative redirects into the dashboard."""
    if not target:
        return "/admin/"
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or not target.startswith("/admin"):
        return "/admin/"
    return target


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, staff: OptionalStaff, next: str | None = None) -> Response:
    if staff is not None:
        return RedirectResponse(safe_next(next), status_code=303)
    return templates.TemplateResponse(request, "admin/login.html", {"next": safe_next(next)})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    db: DbSession,
    settings: SettingsDep,
    email: Annotated[str, Form(max_length=320)],
    password: Annotated[str, Form(max_length=1024)],
    next: Annotated[str | None, Form()] = None,
) -> Response:
    try:
        issued = await AuthService(db, settings).login(
            email,
            password,
            Audience.STAFF,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except InvalidCredentials:
        return templates.TemplateResponse(
            request,
            "admin/login.html",
            {"next": safe_next(next), "email": email, "error": "admin.login.invalid"},
            status_code=401,
        )
    destination = safe_next(next)
    if request.headers.get("hx-request") == "true":
        response: Response = Response(status_code=204, headers={"HX-Redirect": destination})
    else:
        response = RedirectResponse(destination, status_code=303)
    set_session_cookie(response, settings, Audience.STAFF, issued.token, issued.session.expires_at)
    return response


@router.get("/language/{code}")
async def switch_language(
    code: str,
    request: Request,
    settings: SettingsDep,
    db: DbSession,
    next: str | None = None,
) -> RedirectResponse:
    """Remember the dashboard language. ``db`` loads the enabled locale list for this request."""
    enabled = list(getattr(request.state, "enabled_locales", None) or settings.supported_locales)
    default = getattr(request.state, "default_locale", None) or settings.default_locale
    if code not in interface_locales(enabled, default):
        raise HTTPException(status_code=404)
    response = RedirectResponse(safe_next(next), status_code=303)
    response.set_cookie(
        UI_LOCALE_COOKIE,
        code,
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/admin",
    )
    return response


@router.post("/logout")
async def logout(db: DbSession, settings: SettingsDep, staff: OptionalStaff) -> Response:
    if staff is not None:
        await AuthService(db, settings).logout(staff.session)
    response = RedirectResponse("/admin/login", status_code=303)
    clear_session_cookie(response, settings, Audience.STAFF)
    return response


def editor_direction(value: str | None) -> str:
    return "ltr" if value == "ltr" else "rtl"


@router.get("/editor", response_class=HTMLResponse)
async def editor_page(
    request: Request, staff: CurrentStaff, dir: str | None = None
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "admin/editor.html", {"staff": staff, "editor_dir": editor_direction(dir)}
    )


@router.post("/editor/preview", response_class=HTMLResponse)
async def editor_preview(
    request: Request,
    staff: CurrentStaff,
    body: Annotated[str, Form()],
    editor_dir: Annotated[str, Form()] = "rtl",
) -> HTMLResponse:
    direction = editor_direction(editor_dir)
    try:
        html = render_body(json.loads(body))
    except (json.JSONDecodeError, InvalidBody) as exc:
        detail = exc.detail if isinstance(exc, InvalidBody) else "Body is not valid JSON"
        return templates.TemplateResponse(
            request,
            "admin/partials/body_preview.html",
            {"error": detail, "editor_dir": direction},
            status_code=422,
        )
    return templates.TemplateResponse(
        request,
        "admin/partials/body_preview.html",
        {"html": html, "editor_dir": direction, "staff": staff},
    )


_STATUS_ORDER = {status: index for index, status in enumerate(ArticleStatus)}


@router.get("/workflow", response_class=HTMLResponse)
async def workflow_page(request: Request, staff: CurrentStaff) -> HTMLResponse:
    """The desk state machine, for every signed-in staff member."""
    transitions = [
        {
            "action": transition.action,
            "sources": sorted(transition.sources, key=_STATUS_ORDER.__getitem__),
            "target": transition.target,
            "permission": transition.permission.value,
            "requires_reason": transition.requires_reason,
            "owner_may_act": transition.owner_may_act,
        }
        for transition in TRANSITIONS.values()
    ]
    return templates.TemplateResponse(
        request, "admin/workflow.html", {"staff": staff, "transitions": transitions}
    )


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    staff: CurrentStaff,
    notice: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "staff": staff,
            "roles": sorted(staff.grants.role_keys),
            "permissions": sorted(staff.grants.all_permissions()),
            "notice": notice,
            "detail": request.query_params.get("detail"),
        },
    )
