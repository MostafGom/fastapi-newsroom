from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from newsroom.articles.schemas import ArticleOut, ArticleSummaryOut
from newsroom.articles.service import ArticleService
from newsroom.core.db import DbSession
from newsroom.core.errors import NotFound
from newsroom.core.i18n import resolve_api_locale
from newsroom.core.schemas import PROBLEM_RESPONSES, Page, PageParams, Slug, page_params
from newsroom.locales.repository import LocaleRepository
from newsroom.locales.schemas import LocaleOut
from newsroom.taxonomy.schemas import SectionOut
from newsroom.taxonomy.service import TaxonomyService

router = APIRouter(tags=["public"], responses=PROBLEM_RESPONSES)

Locale = Annotated[str, Depends(resolve_api_locale)]
Paging = Annotated[PageParams, Depends(page_params)]


@router.get("/locales", response_model=list[LocaleOut])
async def list_locales(db: DbSession) -> list[LocaleOut]:
    locales = await LocaleRepository(db).list_enabled()
    return [LocaleOut.model_validate(locale) for locale in locales]


@router.get("/sections", response_model=list[SectionOut])
async def list_sections(locale: Locale, db: DbSession) -> list[SectionOut]:
    return await TaxonomyService(db).public_sections(locale)


@router.get("/articles", response_model=Page[ArticleSummaryOut])
async def list_articles(
    locale: Locale,
    paging: Paging,
    db: DbSession,
    section: Annotated[str | None, Query(description="Section slug")] = None,
    tag: Annotated[str | None, Query(description="Tag slug")] = None,
) -> Page[ArticleSummaryOut]:
    return await ArticleService(db).list_public(locale, paging, section_slug=section, tag_slug=tag)


@router.get(
    "/articles/{slug}",
    response_model=ArticleOut,
    responses={
        301: {"description": "Slug changed; follow Location"},
        410: {"description": "Unpublished"},
    },
)
async def get_article(slug: Slug, locale: Locale, db: DbSession) -> ArticleOut | RedirectResponse:
    found = await ArticleService(db).get_public(locale, slug)
    if found.redirect_slug:
        return RedirectResponse(
            f"/api/v1/articles/{found.redirect_slug}?locale={locale}", status_code=301
        )
    if found.article is None:
        raise NotFound("Article not found")
    return found.article


@router.get("/tags/{slug}/articles", response_model=Page[ArticleSummaryOut])
async def list_tag_articles(
    slug: Slug, locale: Locale, paging: Paging, db: DbSession
) -> Page[ArticleSummaryOut]:
    return await ArticleService(db).list_public(locale, paging, section_slug=None, tag_slug=slug)
