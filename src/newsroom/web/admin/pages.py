"""Staff screens for site pages."""

import json
import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from newsroom.articles.body import InvalidBody
from newsroom.auth.dependencies import csrf_protect_web
from newsroom.auth.principal import Principal
from newsroom.authz.dependencies import CurrentStaff
from newsroom.authz.permissions import Perm
from newsroom.core.config import get_settings
from newsroom.core.db import DbSession
from newsroom.core.errors import AppError, NotFound, PermissionDenied
from newsroom.core.i18n import locale_info
from newsroom.pages.models import PageStatus
from newsroom.pages.schemas import PageAdminOut, PageCreate, PageTranslationIn, PageTranslationOut
from newsroom.pages.service import PageService
from newsroom.web.admin.rollups import load_desk
from newsroom.web.templating import templates

router = APIRouter(
    prefix="/admin", dependencies=[Depends(csrf_protect_web)], include_in_schema=False
)

EMPTY_DOC = {"type": "doc", "content": [{"type": "paragraph"}]}


def _require(staff: Principal, perm: Perm) -> None:
    if not staff.grants.has_anywhere(perm):
        raise PermissionDenied(f"Missing permission: {perm.value}")


def _text(form: Any, name: str) -> str:
    value = form.get(name)
    return value.strip() if isinstance(value, str) else ""


def _detail(exc: Exception) -> str:
    if isinstance(exc, AppError):
        return exc.detail or "Invalid input"
    if isinstance(exc, ValidationError):
        return str(exc.errors()[0]["msg"])
    return "Invalid input"


def _back(path: str, exc: Exception) -> RedirectResponse:
    return RedirectResponse(f"{path}?notice=error&detail={quote(_detail(exc))}", status_code=303)


def _parse_body(raw: str) -> dict[str, Any]:
    try:
        document = json.loads(raw) if raw.strip() else EMPTY_DOC
    except json.JSONDecodeError as exc:
        raise InvalidBody("Body is not valid JSON") from exc
    if not isinstance(document, dict):
        raise InvalidBody("Body is not a document")
    return document


def _status(raw: str) -> PageStatus:
    try:
        return PageStatus(raw or PageStatus.DRAFT)
    except ValueError as exc:
        raise ValueError("Invalid status") from exc


def _chosen_locale(locale: str | None) -> str:
    settings = get_settings()
    if locale in settings.supported_locales:
        return locale
    return settings.default_locale


@router.get("/pages", response_class=HTMLResponse)
async def pages_page(
    request: Request,
    staff: CurrentStaff,
    db: DbSession,
    notice: str | None = None,
    detail: str | None = None,
) -> HTMLResponse:
    _require(staff, Perm.PAGE_MANAGE)
    pages = await PageService(db).list_admin(staff)
    return templates.TemplateResponse(
        request,
        "admin/pages.html",
        {"staff": staff, "pages": pages, "notice": notice, "detail": detail},
    )


@router.post("/pages")
async def create_page(request: Request, staff: CurrentStaff, db: DbSession) -> Response:
    _require(staff, Perm.PAGE_MANAGE)
    form = await request.form()
    try:
        created = await PageService(db).create(
            staff,
            PageCreate(
                key=_text(form, "key"),
                sort_order=int(_text(form, "sort_order") or "0"),
            ),
        )
    except PermissionDenied:
        raise
    except (AppError, ValidationError, ValueError) as exc:
        return _back("/admin/pages", exc)
    return RedirectResponse(f"/admin/pages/{created.id}?notice=created", status_code=303)


@router.get("/pages/{page_id}", response_class=HTMLResponse)
async def page_edit(
    page_id: uuid.UUID,
    request: Request,
    staff: CurrentStaff,
    db: DbSession,
    locale: str | None = None,
    notice: str | None = None,
    detail: str | None = None,
) -> HTMLResponse:
    _require(staff, Perm.PAGE_MANAGE)
    pages = await PageService(db).list_admin(staff)
    found = next((item for item in pages if item.id == page_id), None)
    if found is None:
        raise NotFound("Page not found")
    code = _chosen_locale(locale)
    return templates.TemplateResponse(
        request,
        "admin/page.html",
        {
            "staff": staff,
            "page": found,
            "code": code,
            "translation": _translation(found, code),
            "editor_dir": locale_info(code).direction.value,
            "editor_locale": code,
            "body_json": json.dumps(_body(found, code)),
            "notice": notice,
            "detail": detail,
            "can_view_analytics": staff.grants.sections_with(Perm.ANALYTICS_READ) is None,
        },
    )


@router.get("/pages/{page_id}/analytics", response_class=HTMLResponse)
async def page_analytics(
    page_id: uuid.UUID, request: Request, staff: CurrentStaff, db: DbSession
) -> HTMLResponse:
    _require(staff, Perm.PAGE_MANAGE)
    if staff.grants.sections_with(Perm.ANALYTICS_READ) is not None:
        raise PermissionDenied("You cannot view these analytics")
    pages = await PageService(db).list_admin(staff)
    if not any(item.id == page_id for item in pages):
        raise NotFound("Page not found")
    report = await load_desk(request, db, lambda desk: desk.page(page_id))
    return templates.TemplateResponse(
        request,
        "admin/partials/window_analytics.html",
        {"heading": "analytics.page", "lede": "analytics.page_lede", "report": report},
    )


@router.post("/pages/{page_id}")
async def save_page(
    page_id: uuid.UUID, request: Request, staff: CurrentStaff, db: DbSession
) -> Response:
    _require(staff, Perm.PAGE_MANAGE)
    form = await request.form()
    code = _chosen_locale(_text(form, "locale") or None)
    back = f"/admin/pages/{page_id}?locale={code}"
    try:
        await PageService(db).save_translation(
            staff,
            page_id,
            PageTranslationIn(
                locale=code,
                title=_text(form, "title"),
                slug=_text(form, "slug"),
                body=_parse_body(_text(form, "body")),
                status=_status(_text(form, "status")),
            ),
            sort_order=int(_text(form, "sort_order") or "0"),
        )
    except PermissionDenied:
        raise
    except (AppError, ValidationError, ValueError) as exc:
        return _back(back, exc)
    return RedirectResponse(f"{back}&notice=saved", status_code=303)


@router.post("/pages/{page_id}/delete")
async def delete_page(page_id: uuid.UUID, staff: CurrentStaff, db: DbSession) -> Response:
    _require(staff, Perm.PAGE_MANAGE)
    try:
        await PageService(db).delete(staff, page_id)
    except PermissionDenied:
        raise
    except AppError as exc:
        return _back("/admin/pages", exc)
    return RedirectResponse("/admin/pages?notice=saved", status_code=303)


def _translation(page: PageAdminOut, locale: str) -> PageTranslationOut | None:
    return next((item for item in page.translations if item.locale == locale), None)


def _body(page: PageAdminOut, locale: str) -> dict[str, Any]:
    found = _translation(page, locale)
    if found is None:
        return EMPTY_DOC
    return found.body
