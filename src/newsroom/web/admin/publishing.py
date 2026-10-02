"""Staff screens for the media library and the curated homepage."""

import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from newsroom.articles.models import ArticleLocalization
from newsroom.articles.service import ArticleService
from newsroom.articles.workflow import ArticleStatus
from newsroom.auth.dependencies import csrf_protect_web
from newsroom.auth.principal import Principal
from newsroom.authz.dependencies import CurrentStaff
from newsroom.authz.permissions import Perm
from newsroom.core.config import get_settings
from newsroom.core.db import DbSession
from newsroom.core.errors import AppError, PermissionDenied
from newsroom.homepage.service import HomepageService
from newsroom.media.schemas import MediaTranslationIn
from newsroom.media.service import MediaService
from newsroom.web.paging import PageQuery, is_fragment, listing_params, pager_context
from newsroom.web.templating import templates

_PAGE = 40

router = APIRouter(
    prefix="/admin", dependencies=[Depends(csrf_protect_web)], include_in_schema=False
)


def _require(staff: Principal, perm: Perm) -> None:
    if not staff.grants.has_anywhere(perm):
        raise PermissionDenied(f"Missing permission: {perm.value}")


@router.get("/media", response_class=HTMLResponse)
async def media_page(
    request: Request,
    staff: CurrentStaff,
    db: DbSession,
    page: PageQuery = 1,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> HTMLResponse:
    _require(staff, Perm.MEDIA_UPLOAD)
    fragment = is_fragment(request, cursor)
    found = await MediaService(db).list_page(listing_params(_PAGE, page, fragment, cursor))
    return templates.TemplateResponse(
        request,
        "admin/fragments/media.html" if fragment else "admin/media.html",
        {
            "staff": staff,
            "assets": found.items,
            "locales": getattr(request.state, "enabled_locales", None)
            or get_settings().supported_locales,
            "can_manage": staff.grants.has_anywhere(Perm.MEDIA_MANAGE),
            **pager_context(
                path="/admin/media",
                page=page,
                extra=None,
                next_cursor=found.next_cursor,
                fragment=fragment,
                prev_key="manage.previous",
                more_key="manage.more",
            ),
        },
    )


@router.post("/media")
async def upload_media(
    staff: CurrentStaff,
    db: DbSession,
    file: Annotated[UploadFile, File()],
    credit: Annotated[str, Form()] = "",
) -> RedirectResponse:
    _require(staff, Perm.MEDIA_UPLOAD)
    try:
        await MediaService(db).upload(
            staff, await file.read(), credit=credit, filename=file.filename
        )
    except AppError:
        return RedirectResponse("/admin/media?notice=error", status_code=303)
    return RedirectResponse("/admin/media?notice=saved", status_code=303)


@router.post("/media/{asset_id}/caption")
async def caption_media(
    asset_id: uuid.UUID,
    staff: CurrentStaff,
    db: DbSession,
    locale: Annotated[str, Form()],
    caption: Annotated[str, Form()] = "",
    alt_text: Annotated[str, Form()] = "",
) -> RedirectResponse:
    _require(staff, Perm.MEDIA_UPLOAD)
    await MediaService(db).set_translation(
        staff,
        asset_id,
        MediaTranslationIn(locale=locale, caption=caption or None, alt_text=alt_text or None),
    )
    return RedirectResponse("/admin/media?notice=saved", status_code=303)


@router.post("/media/{asset_id}/name")
async def rename_media(
    asset_id: uuid.UUID,
    staff: CurrentStaff,
    db: DbSession,
    filename: Annotated[str, Form()] = "",
) -> RedirectResponse:
    _require(staff, Perm.MEDIA_UPLOAD)
    try:
        await MediaService(db).rename(staff, asset_id, filename)
    except AppError as exc:
        detail = quote(exc.detail or "Could not rename")
        return RedirectResponse(f"/admin/media?notice=error&detail={detail}", status_code=303)
    return RedirectResponse("/admin/media?notice=saved", status_code=303)


@router.post("/media/{asset_id}/delete")
async def delete_media(asset_id: uuid.UUID, staff: CurrentStaff, db: DbSession) -> RedirectResponse:
    _require(staff, Perm.MEDIA_MANAGE)
    try:
        await MediaService(db).delete(staff, asset_id)
    except AppError as exc:
        detail = quote(exc.detail or "Could not delete")
        return RedirectResponse(f"/admin/media?notice=error&detail={detail}", status_code=303)
    return RedirectResponse("/admin/media?notice=saved", status_code=303)


@router.get("/homepage", response_class=HTMLResponse)
async def homepage_page(
    request: Request,
    staff: CurrentStaff,
    db: DbSession,
    locale: str | None = None,
    page: PageQuery = 1,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> HTMLResponse:
    _require(staff, Perm.ARTICLE_PUBLISH)
    code = locale if locale in get_settings().supported_locales else get_settings().default_locale
    fragment = is_fragment(request, cursor)
    found = await ArticleService(db).list_public(
        code,
        listing_params(_PAGE, page, fragment, cursor),
        section_slug=None,
        tag_slug=None,
    )
    curated = await HomepageService(db).public_stories(code) or []
    positions = {item.summary.slug: index for index, item in enumerate(curated, start=1)}
    labels = {item.summary.slug: item.label or "" for item in curated}
    if fragment:
        pinned_slugs = {item.summary.slug for item in curated}
        stories = [item for item in found.items if item.slug not in pinned_slugs]
    else:
        on_page = {item.slug for item in found.items}
        pinned = [item.summary for item in curated if item.summary.slug not in on_page]
        stories = [*pinned, *found.items]
    return templates.TemplateResponse(
        request,
        "admin/fragments/homepage.html" if fragment else "admin/homepage.html",
        {
            "staff": staff,
            "locale": code,
            "locales": get_settings().supported_locales,
            "stories": stories,
            "positions": positions,
            "labels": labels,
            **pager_context(
                path="/admin/homepage",
                page=page,
                extra={"locale": code},
                next_cursor=found.next_cursor,
                fragment=fragment,
                prev_key="manage.previous",
                more_key="manage.more",
            ),
        },
    )


@router.post("/homepage")
async def save_homepage(
    request: Request, staff: CurrentStaff, db: DbSession, locale: Annotated[str, Form()]
) -> RedirectResponse:
    _require(staff, Perm.ARTICLE_PUBLISH)
    form = await request.form()
    chosen: list[tuple[int, str]] = []
    for key, value in form.multi_items():
        if not key.startswith("pos_") or not isinstance(value, str) or not value.strip():
            continue
        try:
            position = int(value)
        except ValueError:
            continue
        chosen.append((position, key.removeprefix("pos_")))
    chosen.sort(key=lambda item: item[0])
    slugs = [slug for _, slug in chosen]
    rows = list(
        (
            await db.scalars(
                select(ArticleLocalization).where(
                    ArticleLocalization.locale == locale,
                    ArticleLocalization.slug.in_(slugs),
                    ArticleLocalization.status == ArticleStatus.PUBLISHED,
                )
            )
        ).all()
    )
    by_slug = {row.slug: row.id for row in rows}
    ids = [by_slug[slug] for _, slug in chosen if slug in by_slug]
    labels = []
    for _, slug in chosen:
        if slug not in by_slug:
            continue
        raw = form.get(f"label_{slug}")
        labels.append(raw.strip() if isinstance(raw, str) else None)
    try:
        await HomepageService(db).replace(staff, locale, ids, labels)
    except AppError:
        return RedirectResponse(f"/admin/homepage?locale={locale}&notice=error", status_code=303)
    return RedirectResponse(f"/admin/homepage?locale={locale}&notice=saved", status_code=303)
