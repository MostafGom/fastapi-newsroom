import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from newsroom.articles.body import plain_text
from newsroom.articles.models import (
    Article,
    ArticleAuthor,
    ArticleLocalization,
    ArticleTag,
    Author,
)
from newsroom.articles.workflow import ArticleStatus
from newsroom.core.schemas import Page, PageParams
from newsroom.search.repository import PostgresSearch
from newsroom.search.schemas import IndexedStory, SearchFilters, SearchHit
from newsroom.taxonomy.models import Section, Tag


class SearchService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.engine = PostgresSearch(db)

    async def sync(self, localization_id: uuid.UUID) -> None:
        """Index a live story, or drop it. Caller commits with the publish or takedown."""
        localization = await self._load(localization_id)
        if (
            localization is None
            or localization.status is not ArticleStatus.PUBLISHED
            or localization.published_revision_id is None
            or localization.published_at is None
        ):
            await self.engine.delete(localization_id)
            return
        published_id = localization.published_revision_id
        revision = next(
            (item for item in localization.revisions if item.id == published_id),
            None,
        )
        if revision is None:
            await self.engine.delete(localization_id)
            return
        article = localization.article
        locale = localization.locale
        section_name, section_slug = _section_label(article.section, locale)
        tag_slugs, tag_names = _tags(article, locale)
        bylines = _bylines(article, locale)
        await self.engine.upsert(
            IndexedStory(
                localization_id=localization.id,
                locale=locale,
                slug=localization.slug,
                title=revision.title,
                excerpt=revision.excerpt,
                body_text=plain_text(revision.body),
                section_id=article.section_id,
                section_slug=section_slug,
                section_name=section_name,
                tag_slugs=tag_slugs,
                extra_text=" ".join([*tag_names, *bylines]),
                published_at=localization.published_at,
            )
        )

    async def search(self, filters: SearchFilters, paging: PageParams) -> Page[SearchHit]:
        return await self.engine.search(filters, paging)

    async def _load(self, localization_id: uuid.UUID) -> ArticleLocalization | None:
        return await self.db.scalar(
            select(ArticleLocalization)
            .where(ArticleLocalization.id == localization_id)
            .options(
                selectinload(ArticleLocalization.revisions),
                selectinload(ArticleLocalization.article)
                .selectinload(Article.section)
                .selectinload(Section.translations),
                selectinload(ArticleLocalization.article)
                .selectinload(Article.article_authors)
                .selectinload(ArticleAuthor.author)
                .selectinload(Author.translations),
                selectinload(ArticleLocalization.article)
                .selectinload(Article.article_tags)
                .selectinload(ArticleTag.tag)
                .selectinload(Tag.translations),
            )
        )


def _named(rows: list, locale: str) -> tuple[str, str] | None:
    item = next((row for row in rows if row.locale == locale), None)
    if item is None and rows:
        item = rows[0]
    if item is None:
        return None
    return item.name, item.slug


def _section_label(section: Section, locale: str) -> tuple[str, str]:
    named = _named(section.translations, locale)
    if named is None:
        return section.key, section.key
    return named


def _tags(article: Article, locale: str) -> tuple[list[str], list[str]]:
    slugs: list[str] = []
    names: list[str] = []
    for link in article.article_tags:
        named = _named(link.tag.translations, locale)
        if named is None:
            continue
        name, slug = named
        slugs.append(slug)
        names.append(name)
    return slugs, names


def _bylines(article: Article, locale: str) -> list[str]:
    names: list[str] = []
    for link in sorted(article.article_authors, key=lambda item: item.position):
        rows = link.author.translations
        item = next((row for row in rows if row.locale == locale), None)
        if item is None and rows:
            item = rows[0]
        if item is not None:
            names.append(item.display_name)
    return names
