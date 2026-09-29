import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Path, Query, Request
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
from newsroom.comments.service import CommentService
from newsroom.core.config import get_settings
from newsroom.core.db import DbSession
from newsroom.core.errors import NotFound
from newsroom.core.schemas import PageParams
from newsroom.homepage.service import HomepageService
from newsroom.media.service import MediaService
from newsroom.search.schemas import SearchFilters
from newsroom.search.service import SearchService
from newsroom.taxonomy.service import TaxonomyService
from newsroom.users.service import UserService
from newsroom.web.templating import templates

router = APIRouter(dependencies=[Depends(csrf_protect_web)], include_in_schema=False)


async def supported_locale(
    locale: Annotated[str, Path(max_length=10)], request: Request, db: DbSession
) -> str:
    from newsroom.core.site import load_site_context

    await load_site_context(request, db)
    enabled = getattr(request.state, "enabled_locales", None) or get_settings().supported_locales
    if locale not in enabled:
        raise HTTPException(status_code=404)
    request.state.nav_sections = await TaxonomyService(db).public_sections(locale)
    return locale


LocaleParam = Annotated[str, Depends(supported_locale)]


def _section_name(nodes, slug: str) -> str | None:
    for node in nodes:
        if node.slug == slug:
            return node.name
        found = _section_name(node.children, slug)
        if found:
            return found
    return None


@router.get("/")
async def root(request: Request, db: DbSession) -> RedirectResponse:
    from newsroom.core.site import load_site_context

    await load_site_context(request, db)
    default = getattr(request.state, "default_locale", None) or get_settings().default_locale
    return RedirectResponse(f"/{default}/", status_code=307)


@router.get("/{locale}/", response_class=HTMLResponse)
async def home(
    request: Request, locale: LocaleParam, reader: OptionalReader, db: DbSession
) -> HTMLResponse:
    curated = await HomepageService(db).public_stories(locale)
    labels: dict[str, str] = {}
    if curated is None:
        page = await ArticleService(db).list_public(
            locale, PageParams(limit=20, cursor=None), section_slug=None, tag_slug=None
        )
        articles = page.items
    else:
        articles = [item.summary for item in curated]
        labels = {item.summary.slug: item.label for item in curated if item.label}
    return templates.TemplateResponse(
        request, "public/home.html", {"reader": reader, "articles": articles, "labels": labels}
    )


@router.get("/{locale}/search", response_class=HTMLResponse)
async def search(
    request: Request,
    locale: LocaleParam,
    reader: OptionalReader,
    db: DbSession,
    q: Annotated[str, Query(max_length=200)] = "",
    section: Annotated[str | None, Query(max_length=160)] = None,
    tag: Annotated[str | None, Query(max_length=160)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> HTMLResponse:
    page = await SearchService(db).search(
        SearchFilters(locale=locale, text=q, section_slug=section, tag_slug=tag),
        PageParams(limit=20, cursor=cursor),
    )
    return templates.TemplateResponse(
        request,
        "public/search.html",
        {"reader": reader, "hits": page.items, "query": q, "next_cursor": page.next_cursor},
    )


@router.get("/{locale}/section/{slug}", response_class=HTMLResponse)
async def section(
    request: Request, locale: LocaleParam, slug: str, reader: OptionalReader, db: DbSession
) -> HTMLResponse:
    page = await ArticleService(db).list_public(
        locale, PageParams(limit=20, cursor=None), section_slug=slug, tag_slug=None
    )
    sections = getattr(request.state, "nav_sections", [])
    return templates.TemplateResponse(
        request,
        "public/home.html",
        {
            "reader": reader,
            "articles": page.items,
            "heading": _section_name(sections, slug) or slug,
            "current_section": slug,
            "empty_key": "home.empty",
        },
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
        {
            "reader": reader,
            "articles": page.items,
            "heading": found.name,
            "empty_key": "tag.empty",
        },
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
    comments = await CommentService(db).list_for_slug(
        locale, story.slug, reader.user.id if reader else None
    )
    lead_alt = None
    lead_caption = None
    if story.lead_image_url:
        asset_id = uuid.UUID(story.lead_image_url.removeprefix("/media/"))
        lead_alt, lead_caption = await MediaService(db).caption(asset_id, locale)
    return templates.TemplateResponse(
        request,
        "public/article.html",
        {
            "reader": reader,
            "article": story,
            "bookmarked": bookmarked,
            "comments": comments,
            "lead_alt": lead_alt,
            "lead_caption": lead_caption,
        },
    )


@router.post("/{locale}/article/{slug}/comments")
async def post_comment(
    locale: LocaleParam,
    slug: str,
    reader: CurrentReader,
    db: DbSession,
    body: Annotated[str, Form(max_length=2000)] = "",
) -> RedirectResponse:
    await CommentService(db).add_for_slug(reader, locale, slug, body)
    return RedirectResponse(f"/{locale}/article/{slug}", status_code=303)


@router.post("/{locale}/article/{slug}/comments/{comment_id}/hide")
async def hide_comment(
    locale: LocaleParam,
    slug: str,
    comment_id: uuid.UUID,
    reader: CurrentReader,
    db: DbSession,
) -> RedirectResponse:
    await CommentService(db).hide(reader, comment_id)
    return RedirectResponse(f"/{locale}/article/{slug}", status_code=303)


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
