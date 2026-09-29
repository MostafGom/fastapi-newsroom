"""Staff screens for sections, tags, accounts, and the audit log."""

import uuid
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from starlette.datastructures import FormData

from newsroom.audit.service import AuditService
from newsroom.auth.dependencies import csrf_protect_web
from newsroom.auth.principal import Principal
from newsroom.authz.dependencies import CurrentStaff
from newsroom.authz.permissions import Perm
from newsroom.core.config import get_settings
from newsroom.core.db import DbSession
from newsroom.core.errors import AppError, PermissionDenied
from newsroom.core.schemas import PageParams
from newsroom.taxonomy.schemas import (
    SectionAdminOut,
    SectionCreate,
    SectionTranslationIn,
    SectionUpdate,
    TagCreate,
    TagTranslationIn,
)
from newsroom.taxonomy.service import TaxonomyService
from newsroom.users.models import UserKind, UserStatus
from newsroom.users.schemas import RoleGrantCreate, StaffCreate, UserUpdate
from newsroom.users.service import UserService
from newsroom.web.templating import templates

router = APIRouter(
    prefix="/admin", dependencies=[Depends(csrf_protect_web)], include_in_schema=False
)

_PAGE = 40


def _require(staff: Principal, perm: Perm) -> None:
    if not staff.grants.has_anywhere(perm):
        raise PermissionDenied(f"Missing permission: {perm.value}")


def _text(form: FormData, name: str) -> str:
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


def _section_translations(form: FormData) -> list[SectionTranslationIn]:
    return [
        SectionTranslationIn.model_validate(row)
        for row in _locale_rows(form, with_description=True)
    ]


def _tag_translations(form: FormData) -> list[TagTranslationIn]:
    return [
        TagTranslationIn.model_validate(row) for row in _locale_rows(form, with_description=False)
    ]


def _locale_rows(form: FormData, *, with_description: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for locale in get_settings().supported_locales:
        name = _text(form, f"name_{locale}")
        slug = _text(form, f"slug_{locale}")
        description = _text(form, f"description_{locale}") if with_description else ""
        if not name and not slug and not description:
            continue
        row: dict[str, Any] = {"locale": locale, "name": name, "slug": slug}
        if with_description:
            row["description"] = description or None
        rows.append(row)
    return rows


def _filled(translations: list[Any]) -> dict[str, dict[str, str]]:
    found = {item.locale: item for item in translations}
    out: dict[str, dict[str, str]] = {}
    for code in get_settings().supported_locales:
        item = found.get(code)
        out[code] = {
            "name": item.name if item else "",
            "slug": item.slug if item else "",
            "description": getattr(item, "description", None) or "" if item else "",
        }
    return out


def _section_view(section: SectionAdminOut, keys: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": section.id,
        "key": section.key,
        "sort_order": section.sort_order,
        "is_active": section.is_active,
        "parent_key": keys.get(section.parent_id) if section.parent_id else None,
        "locales": _filled(section.translations),
    }


@router.get("/sections", response_class=HTMLResponse)
async def sections_page(
    request: Request,
    staff: CurrentStaff,
    db: DbSession,
    notice: str | None = None,
    detail: str | None = None,
) -> HTMLResponse:
    _require(staff, Perm.SECTION_MANAGE)
    rows = await TaxonomyService(db).list_admin_sections()
    keys = {row.id: row.key for row in rows}
    return templates.TemplateResponse(
        request,
        "admin/sections.html",
        {
            "staff": staff,
            "sections": [_section_view(row, keys) for row in rows],
            "notice": notice,
            "detail": detail,
        },
    )


@router.post("/sections")
async def create_section(request: Request, staff: CurrentStaff, db: DbSession) -> Response:
    _require(staff, Perm.SECTION_MANAGE)
    form = await request.form()
    try:
        await TaxonomyService(db).create_section(
            SectionCreate(
                key=_text(form, "key"),
                sort_order=int(_text(form, "sort_order") or "0"),
                translations=_section_translations(form),
            )
        )
    except (AppError, ValidationError, ValueError) as exc:
        return _back("/admin/sections", exc)
    return RedirectResponse("/admin/sections?notice=created", status_code=303)


@router.post("/sections/{section_id}")
async def update_section(
    section_id: uuid.UUID, request: Request, staff: CurrentStaff, db: DbSession
) -> Response:
    _require(staff, Perm.SECTION_MANAGE)
    form = await request.form()
    try:
        rows = _section_translations(form)
        if not rows:
            raise ValueError
        await TaxonomyService(db).update_section(
            section_id,
            SectionUpdate(
                sort_order=int(_text(form, "sort_order") or "0"),
                is_active=_text(form, "is_active") == "1",
                translations=rows,
            ),
        )
    except (AppError, ValidationError, ValueError) as exc:
        return _back("/admin/sections", exc)
    return RedirectResponse("/admin/sections?notice=saved", status_code=303)


@router.get("/tags", response_class=HTMLResponse)
async def tags_page(
    request: Request,
    staff: CurrentStaff,
    db: DbSession,
    notice: str | None = None,
    detail: str | None = None,
    cursor: str | None = None,
) -> HTMLResponse:
    _require(staff, Perm.TAG_MANAGE)
    page = await TaxonomyService(db).list_tags(PageParams(limit=_PAGE, cursor=cursor), q=None)
    tags = [
        {"id": tag.id, "key": tag.key, "locales": _filled(tag.translations)} for tag in page.items
    ]
    return templates.TemplateResponse(
        request,
        "admin/tags.html",
        {
            "staff": staff,
            "tags": tags,
            "next_cursor": page.next_cursor,
            "notice": notice,
            "detail": detail,
        },
    )


@router.post("/tags")
async def create_tag(request: Request, staff: CurrentStaff, db: DbSession) -> Response:
    _require(staff, Perm.TAG_MANAGE)
    form = await request.form()
    try:
        await TaxonomyService(db).create_tag(
            TagCreate(key=_text(form, "key"), translations=_tag_translations(form))
        )
    except (AppError, ValidationError, ValueError) as exc:
        return _back("/admin/tags", exc)
    return RedirectResponse("/admin/tags?notice=created", status_code=303)


@router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    staff: CurrentStaff,
    db: DbSession,
    kind: UserKind | None = None,
    q: str | None = None,
    cursor: str | None = None,
    notice: str | None = None,
    detail: str | None = None,
) -> HTMLResponse:
    _require(staff, Perm.USER_READ)
    page = await UserService(db).list_users(
        PageParams(limit=_PAGE, cursor=cursor), kind=kind, status=None, q=q
    )
    return templates.TemplateResponse(
        request,
        "admin/users.html",
        {
            "staff": staff,
            "users": page.items,
            "kind_value": kind.value if kind else "",
            "query": q or "",
            "next_cursor": page.next_cursor,
            "can_manage": staff.grants.has_anywhere(Perm.USER_MANAGE),
            "notice": notice,
            "detail": detail,
        },
    )


@router.post("/users")
async def create_user(request: Request, staff: CurrentStaff, db: DbSession) -> Response:
    _require(staff, Perm.USER_MANAGE)
    form = await request.form()
    password = form.get("password")
    try:
        created = await UserService(db).create_staff_account(
            staff,
            StaffCreate(
                email=_text(form, "email"),
                display_name=_text(form, "display_name"),
                job_title=_text(form, "job_title") or None,
                password=password if isinstance(password, str) else "",
            ),
        )
    except (AppError, ValidationError, ValueError) as exc:
        return _back("/admin/users", exc)
    return RedirectResponse(f"/admin/users/{created.id}?notice=created", status_code=303)


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def user_page(
    user_id: uuid.UUID,
    request: Request,
    staff: CurrentStaff,
    db: DbSession,
    notice: str | None = None,
    detail: str | None = None,
) -> HTMLResponse:
    _require(staff, Perm.USER_READ)
    service = UserService(db)
    account = await service.get_user(user_id)
    grants = await service.list_role_grants(user_id)
    roles = await service.list_roles()
    sections = await TaxonomyService(db).list_admin_sections()
    keys = {row.id: row.key for row in sections}
    grant_rows = [
        {
            "id": grant.id,
            "role_key": grant.role_key,
            "scope": keys.get(grant.section_id) if grant.section_id else None,
        }
        for grant in grants
    ]
    return templates.TemplateResponse(
        request,
        "admin/user.html",
        {
            "staff": staff,
            "account": account,
            "grants": grant_rows,
            "roles": [role for role in roles if role.rank < staff.grants.max_rank],
            "sections": sections,
            "statuses": list(UserStatus),
            "can_manage": staff.grants.has_anywhere(Perm.USER_MANAGE),
            "can_assign": staff.grants.has_anywhere(Perm.ROLE_ASSIGN),
            "notice": notice,
            "detail": detail,
        },
    )


@router.post("/users/{user_id}")
async def update_user(
    user_id: uuid.UUID, request: Request, staff: CurrentStaff, db: DbSession
) -> Response:
    _require(staff, Perm.USER_MANAGE)
    form = await request.form()
    try:
        status_text = _text(form, "status")
        await UserService(db).update_user(
            staff,
            user_id,
            UserUpdate(
                status=UserStatus(status_text) if status_text else None,
                display_name=_text(form, "display_name") or None,
                job_title=_text(form, "job_title") or None,
            ),
        )
    except (AppError, ValidationError, ValueError) as exc:
        return _back(f"/admin/users/{user_id}", exc)
    return RedirectResponse(f"/admin/users/{user_id}?notice=saved", status_code=303)


@router.post("/users/{user_id}/roles")
async def grant_user_role(
    user_id: uuid.UUID, request: Request, staff: CurrentStaff, db: DbSession
) -> Response:
    _require(staff, Perm.ROLE_ASSIGN)
    form = await request.form()
    section = _text(form, "section_id")
    try:
        await UserService(db).grant_role(
            staff,
            user_id,
            RoleGrantCreate(
                role_key=_text(form, "role_key"),
                section_id=uuid.UUID(section) if section else None,
            ),
        )
    except (AppError, ValidationError, ValueError) as exc:
        return _back(f"/admin/users/{user_id}", exc)
    return RedirectResponse(f"/admin/users/{user_id}?notice=granted", status_code=303)


@router.post("/users/{user_id}/roles/{user_role_id}/revoke")
async def revoke_user_role(
    user_id: uuid.UUID, user_role_id: uuid.UUID, staff: CurrentStaff, db: DbSession
) -> Response:
    _require(staff, Perm.ROLE_ASSIGN)
    try:
        await UserService(db).revoke_role(staff, user_id, user_role_id)
    except (AppError, ValidationError, ValueError) as exc:
        return _back(f"/admin/users/{user_id}", exc)
    return RedirectResponse(f"/admin/users/{user_id}?notice=revoked", status_code=303)


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(
    request: Request,
    staff: CurrentStaff,
    db: DbSession,
    action: str | None = None,
    entity_type: str | None = None,
    cursor: str | None = None,
) -> HTMLResponse:
    _require(staff, Perm.AUDIT_READ)
    page = await AuditService(db).list_events(
        PageParams(limit=_PAGE, cursor=cursor),
        action=action or None,
        entity_type=entity_type or None,
    )
    filters = {"action": action or "", "entity_type": entity_type or ""}
    nxt = None
    if page.next_cursor:
        nxt = "/admin/audit?" + urlencode({**filters, "cursor": page.next_cursor})
    return templates.TemplateResponse(
        request,
        "admin/audit.html",
        {
            "staff": staff,
            "events": page.items,
            "filters": filters,
            "next_url": nxt,
        },
    )
