import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Path, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from newsroom.articles.service import ArticleService
from newsroom.auth.dependencies import (
    CurrentReader,
    OptionalReader,
    SettingsDep,
    clear_session_cookie,
    csrf_protect_web,
    set_session_cookie,
)
from newsroom.auth.schemas import Audience
from newsroom.auth.service import AuthService, InvalidCredentials
from newsroom.core.config import get_settings
from newsroom.core.db import DbSession
from newsroom.core.errors import NotFound
from newsroom.core.schemas import PageParams
from newsroom.taxonomy.service import TaxonomyService
from newsroom.users.service import UserService
from newsroom.web.templating import templates

router = APIRouter(dependencies=[Depends(csrf_protect_web)], include_in_schema=False)


def supported_locale(locale: Annotated[str, Path(max_length=10)]) -> str:
    if locale not in get_settings().supported_locales:
        raise HTTPException(status_code=404)
    return locale


LocaleParam = Annotated[str, Depends(supported_locale)]


@router.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(f"/{get_settings().default_locale}/", status_code=307)


@router.get("/{locale}/", response_class=HTMLResponse)
async def home(
    request: Request, locale: LocaleParam, reader: OptionalReader, db: DbSession
) -> HTMLResponse:
    page = await ArticleService(db).list_public(
        locale, PageParams(limit=20, cursor=None), section_slug=None, tag_slug=None
    )
    return templates.TemplateResponse(
        request, "public/home.html", {"reader": reader, "articles": page.items}
    )


@router.get("/{locale}/section/{slug}", response_class=HTMLResponse)
async def section(
    request: Request, locale: LocaleParam, slug: str, reader: OptionalReader, db: DbSession
) -> HTMLResponse:
    page = await ArticleService(db).list_public(
        locale, PageParams(limit=20, cursor=None), section_slug=slug, tag_slug=None
    )
    return templates.TemplateResponse(
        request, "public/home.html", {"reader": reader, "articles": page.items}
    )


@router.get("/{locale}/tag/{slug}", response_class=HTMLResponse)
async def tag(
    request: Request, locale: LocaleParam, slug: str, reader: OptionalReader, db: DbSession
) -> HTMLResponse:
    found = await TaxonomyService(db).public_tag(locale, slug)
    page = await ArticleService(db).list_public(
        locale, PageParams(limit=20, cursor=None), section_slug=None, tag_slug=slug
    )
    return templates.TemplateResponse(
        request,
        "public/home.html",
        {"reader": reader, "articles": page.items, "heading": found.name},
    )


@router.get("/{locale}/article/{slug}", response_class=HTMLResponse)
async def article(
    request: Request, locale: LocaleParam, slug: str, reader: OptionalReader, db: DbSession
) -> Response:
    found = await ArticleService(db).get_public(locale, slug)
    if found.redirect_slug:
        return RedirectResponse(f"/{locale}/article/{found.redirect_slug}", status_code=301)
    story = found.article
    if story is None:
        raise NotFound("Article not found")
    bookmarked = False
    if reader is not None:
        saved = await ArticleService(db).list_bookmarks(reader.user.id, locale)
        bookmarked = any(item.id == story.id for item in saved)
    return templates.TemplateResponse(
        request,
        "public/article.html",
        {"reader": reader, "article": story, "bookmarked": bookmarked},
    )


@router.post("/{locale}/article/{slug}/bookmark")
async def bookmark_article(
    locale: LocaleParam, slug: str, reader: CurrentReader, db: DbSession
) -> RedirectResponse:
    found = await ArticleService(db).get_public(locale, slug)
    if found.article is not None:
        await ArticleService(db).bookmark(reader.user.id, found.article.id)
    return RedirectResponse(f"/{locale}/article/{slug}", status_code=303)


@router.get("/{locale}/login", response_class=HTMLResponse)
async def login_form(request: Request, locale: LocaleParam, reader: OptionalReader) -> Response:
    if reader is not None:
        return RedirectResponse(f"/{locale}/account", status_code=303)
    return templates.TemplateResponse(request, "public/login.html", {"mode": "login"})


@router.post("/{locale}/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    locale: LocaleParam,
    db: DbSession,
    settings: SettingsDep,
    email: Annotated[str, Form(max_length=320)],
    password: Annotated[str, Form(max_length=1024)],
) -> Response:
    try:
        issued = await AuthService(db, settings).login(
            email, password, Audience.READER, ip=request.client.host if request.client else None
        )
    except InvalidCredentials:
        return templates.TemplateResponse(
            request,
            "public/login.html",
            {"mode": "login", "error": "admin.login.invalid"},
            status_code=401,
        )
    response = RedirectResponse(f"/{locale}/account", status_code=303)
    set_session_cookie(response, settings, Audience.READER, issued.token, issued.session.expires_at)
    return response


@router.get("/{locale}/register", response_class=HTMLResponse)
async def register_form(request: Request, locale: LocaleParam) -> HTMLResponse:
    return templates.TemplateResponse(request, "public/login.html", {"mode": "register"})


@router.post("/{locale}/register")
async def register_submit(
    request: Request,
    locale: LocaleParam,
    db: DbSession,
    settings: SettingsDep,
    email: Annotated[str, Form(max_length=320)],
    password: Annotated[str, Form(min_length=10, max_length=1024)],
    display_name: Annotated[str | None, Form()] = None,
) -> Response:
    await UserService(db).register_reader(email, password, display_name, locale)
    issued = await AuthService(db, settings).login(email, password, Audience.READER)
    response = RedirectResponse(f"/{locale}/account", status_code=303)
    set_session_cookie(response, settings, Audience.READER, issued.token, issued.session.expires_at)
    return response


@router.post("/{locale}/logout")
async def logout(
    locale: LocaleParam, db: DbSession, settings: SettingsDep, reader: OptionalReader
) -> Response:
    if reader is not None:
        await AuthService(db, settings).logout(reader.session)
    response = RedirectResponse(f"/{locale}/", status_code=303)
    clear_session_cookie(response, settings, Audience.READER)
    return response


@router.get("/{locale}/account", response_class=HTMLResponse)
async def account(
    request: Request, locale: LocaleParam, reader: CurrentReader, db: DbSession
) -> HTMLResponse:
    profile = reader.user.reader_profile
    bookmarks = await ArticleService(db).list_bookmarks(reader.user.id, locale)
    return templates.TemplateResponse(
        request,
        "public/account.html",
        {"profile": profile, "bookmarks": bookmarks, "reader": reader},
    )


@router.post("/{locale}/account")
async def account_save(
    locale: LocaleParam,
    reader: CurrentReader,
    db: DbSession,
    display_name: Annotated[str, Form(max_length=120)] = "",
    preferred_locale: Annotated[str | None, Form()] = None,
    newsletter_opt_in: Annotated[str | None, Form()] = None,
) -> RedirectResponse:
    await UserService(db).update_reader_profile(
        reader.user,
        display_name=display_name or None,
        preferred_locale=preferred_locale,
        newsletter_opt_in=newsletter_opt_in == "1",
    )
    return RedirectResponse(f"/{locale}/account", status_code=303)


@router.post("/{locale}/account/bookmarks/{article_id}/remove")
async def remove_bookmark(
    locale: LocaleParam, article_id: str, reader: CurrentReader, db: DbSession
) -> RedirectResponse:
    await ArticleService(db).unbookmark(reader.user.id, uuid.UUID(article_id))
    return RedirectResponse(f"/{locale}/account", status_code=303)
