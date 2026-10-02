"""Staff screens for sections, tags, accounts, and the audit log."""

import uuid
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from starlette.datastructures import FormData

from newsroom.articles.authors import AuthorCreate, AuthorService, AuthorTranslationIn
from newsroom.articles.models import AuthorKind
from newsroom.audit.service import AuditService
from newsroom.auth.dependencies import csrf_protect_web
from newsroom.auth.principal import Principal
from newsroom.authz.dependencies import CurrentStaff
from newsroom.authz.permissions import Perm
from newsroom.core.config import get_settings
from newsroom.core.db import DbSession
from newsroom.core.errors import AppError, PermissionDenied
from newsroom.core.i18n import TextDirection
from newsroom.locales.service import LocaleCreate, LocaleService
from newsroom.settings.service import SettingsService, SiteSettingsUpdate
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
from newsroom.users.schemas import RoleCreate, RoleGrantCreate, StaffCreate, UserUpdate
from newsroom.users.service import UserService
from newsroom.web.paging import PageQuery, is_fragment, listing_params, pager_context
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
    page: PageQuery = 1,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> HTMLResponse:
    _require(staff, Perm.TAG_MANAGE)
    fragment = is_fragment(request, cursor)
    found = await TaxonomyService(db).list_tags(
        listing_params(_PAGE, page, fragment, cursor),
        q=None,
    )
    tags = [
        {"id": tag.id, "key": tag.key, "locales": _filled(tag.translations)} for tag in found.items
    ]
    return templates.TemplateResponse(
        request,
        "admin/fragments/tags.html" if fragment else "admin/tags.html",
        {
            "staff": staff,
            "tags": tags,
            "notice": notice,
            "detail": detail,
            **pager_context(
                path="/admin/tags",
                page=page,
                extra=None,
                next_cursor=found.next_cursor,
                fragment=fragment,
                prev_key="manage.previous",
                more_key="manage.more",
            ),
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
    page: PageQuery = 1,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    notice: str | None = None,
    detail: str | None = None,
) -> HTMLResponse:
    _require(staff, Perm.USER_READ)
    fragment = is_fragment(request, cursor)
    found = await UserService(db).list_users(
        listing_params(_PAGE, page, fragment, cursor),
        kind=kind,
        status=None,
        q=q,
    )
    return templates.TemplateResponse(
        request,
        "admin/fragments/users.html" if fragment else "admin/users.html",
        {
            "staff": staff,
            "users": found.items,
            "kind_value": kind.value if kind else "",
            "query": q or "",
            "can_manage": staff.grants.has_anywhere(Perm.USER_MANAGE),
            "notice": notice,
            "detail": detail,
            **pager_context(
                path="/admin/users",
                page=page,
                extra={"kind": kind.value if kind else "", "q": q or ""},
                next_cursor=found.next_cursor,
                fragment=fragment,
                prev_key="manage.previous",
                more_key="manage.more",
            ),
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
    page: PageQuery = 1,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> HTMLResponse:
    _require(staff, Perm.AUDIT_READ)
    fragment = is_fragment(request, cursor)
    found = await AuditService(db).list_events(
        listing_params(_PAGE, page, fragment, cursor),
        action=action or None,
        entity_type=entity_type or None,
    )
    filters = {"action": action or "", "entity_type": entity_type or ""}
    return templates.TemplateResponse(
        request,
        "admin/fragments/audit.html" if fragment else "admin/audit.html",
        {
            "staff": staff,
            "events": found.items,
            "filters": filters,
            **pager_context(
                path="/admin/audit",
                page=page,
                extra=filters,
                next_cursor=found.next_cursor,
                fragment=fragment,
                prev_key="manage.previous",
                more_key="manage.more",
            ),
        },
    )


@router.post("/tags/merge")
async def merge_tags(request: Request, staff: CurrentStaff, db: DbSession) -> Response:
    _require(staff, Perm.TAG_MANAGE)
    form = await request.form()
    try:
        await TaxonomyService(db).merge_tags(
            staff, uuid.UUID(_text(form, "source_id")), uuid.UUID(_text(form, "target_id"))
        )
    except (AppError, ValidationError, ValueError) as exc:
        return _back("/admin/tags", exc)
    return RedirectResponse("/admin/tags?notice=saved", status_code=303)


@router.get("/authors", response_class=HTMLResponse)
async def authors_page(
    request: Request,
    staff: CurrentStaff,
    db: DbSession,
    notice: str | None = None,
    detail: str | None = None,
) -> HTMLResponse:
    _require(staff, Perm.ARTICLE_CREATE)
    authors = await AuthorService(db).list_bylines()
    return templates.TemplateResponse(
        request,
        "admin/authors.html",
        {
            "staff": staff,
            "authors": authors,
            "kinds": [AuthorKind.CONTRIBUTOR, AuthorKind.AGENCY],
            "notice": notice,
            "detail": detail,
        },
    )


@router.post("/authors")
async def create_author(request: Request, staff: CurrentStaff, db: DbSession) -> Response:
    _require(staff, Perm.ARTICLE_CREATE)
    form = await request.form()
    translations = []
    for code in request.state.enabled_locales:
        name = _text(form, f"name_{code}")
        slug = _text(form, f"slug_{code}")
        if name and slug:
            translations.append(
                AuthorTranslationIn(locale=code, display_name=name, slug=slug, bio=None)
            )
    try:
        await AuthorService(db).create(
            staff,
            AuthorCreate(
                kind=AuthorKind(_text(form, "kind")),
                key=_text(form, "key"),
                translations=translations,
            ),
        )
    except (AppError, ValidationError, ValueError) as exc:
        return _back("/admin/authors", exc)
    return RedirectResponse("/admin/authors?notice=created", status_code=303)


@router.post("/authors/{author_id}/delete")
async def delete_author(author_id: uuid.UUID, staff: CurrentStaff, db: DbSession) -> Response:
    try:
        await AuthorService(db).delete(staff, author_id)
    except (AppError, ValueError) as exc:
        return _back("/admin/authors", exc)
    return RedirectResponse("/admin/authors?notice=saved", status_code=303)


@router.get("/locales", response_class=HTMLResponse)
async def locales_page(
    request: Request,
    staff: CurrentStaff,
    db: DbSession,
    notice: str | None = None,
    detail: str | None = None,
) -> HTMLResponse:
    _require(staff, Perm.LOCALE_MANAGE)
    rows = await LocaleService(db).list_all()
    return templates.TemplateResponse(
        request,
        "admin/locales.html",
        {
            "staff": staff,
            "rows": rows,
            "directions": list(TextDirection),
            "notice": notice,
            "detail": detail,
        },
    )


@router.post("/locales")
async def create_locale(request: Request, staff: CurrentStaff, db: DbSession) -> Response:
    _require(staff, Perm.LOCALE_MANAGE)
    form = await request.form()
    try:
        await LocaleService(db).create(
            staff,
            LocaleCreate(
                code=_text(form, "code"),
                name=_text(form, "name"),
                native_name=_text(form, "native_name"),
                direction=TextDirection(_text(form, "direction")),
                sort_order=int(_text(form, "sort_order") or "0"),
            ),
        )
    except (AppError, ValidationError, ValueError) as exc:
        return _back("/admin/locales", exc)
    return RedirectResponse("/admin/locales?notice=created", status_code=303)


@router.post("/locales/{code}/default")
async def make_default_locale(code: str, staff: CurrentStaff, db: DbSession) -> Response:
    _require(staff, Perm.LOCALE_MANAGE)
    try:
        await LocaleService(db).set_default(staff, code)
    except (AppError, ValueError) as exc:
        return _back("/admin/locales", exc)
    return RedirectResponse("/admin/locales?notice=saved", status_code=303)


@router.post("/locales/{code}/enabled")
async def toggle_locale(
    code: str, request: Request, staff: CurrentStaff, db: DbSession
) -> Response:
    _require(staff, Perm.LOCALE_MANAGE)
    form = await request.form()
    try:
        await LocaleService(db).set_enabled(staff, code, _text(form, "enabled") == "1")
    except (AppError, ValueError) as exc:
        return _back("/admin/locales", exc)
    return RedirectResponse("/admin/locales?notice=saved", status_code=303)


@router.get("/roles", response_class=HTMLResponse)
async def roles_page(
    request: Request,
    staff: CurrentStaff,
    db: DbSession,
    notice: str | None = None,
    detail: str | None = None,
) -> HTMLResponse:
    _require(staff, Perm.ROLE_MANAGE)
    roles = await UserService(db).list_roles()
    return templates.TemplateResponse(
        request,
        "admin/roles.html",
        {
            "staff": staff,
            "roles": roles,
            "permissions": [item.value for item in Perm],
            "notice": notice,
            "detail": detail,
        },
    )


@router.post("/roles")
async def create_role(request: Request, staff: CurrentStaff, db: DbSession) -> Response:
    _require(staff, Perm.ROLE_MANAGE)
    form = await request.form()
    selected = form.getlist("permissions")
    try:
        await UserService(db).create_role(
            staff,
            RoleCreate(
                key=_text(form, "key"),
                name=_text(form, "name"),
                description=_text(form, "description") or None,
                rank=int(_text(form, "rank") or "10"),
                permissions=[item for item in selected if isinstance(item, str)],
            ),
        )
    except (AppError, ValidationError, ValueError) as exc:
        return _back("/admin/roles", exc)
    return RedirectResponse("/admin/roles?notice=created", status_code=303)


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    staff: CurrentStaff,
    db: DbSession,
    notice: str | None = None,
    detail: str | None = None,
) -> HTMLResponse:
    _require(staff, Perm.SETTINGS_MANAGE)
    current = await SettingsService(db).get()
    return templates.TemplateResponse(
        request,
        "admin/settings.html",
        {"staff": staff, "current": current, "notice": notice, "detail": detail},
    )


@router.post("/settings")
async def save_settings(request: Request, staff: CurrentStaff, db: DbSession) -> Response:
    _require(staff, Perm.SETTINGS_MANAGE)
    form = await request.form()
    try:
        await SettingsService(db).update(
            staff,
            SiteSettingsUpdate(
                site_name=_text(form, "site_name"),
                registration_enabled=_text(form, "registration_enabled") == "1",
            ),
        )
    except (AppError, ValidationError, ValueError) as exc:
        return _back("/admin/settings", exc)
    return RedirectResponse("/admin/settings?notice=saved", status_code=303)
