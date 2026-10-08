import uuid

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.articles.models import ArticleLocalization, ArticleTag
from newsroom.articles.workflow import ArticleStatus
from newsroom.audit.service import record_event
from newsroom.auth.principal import Principal
from newsroom.core.errors import Conflict, NotFound
from newsroom.core.schemas import Page, PageParams
from newsroom.search.service import SearchService
from newsroom.taxonomy.models import Section, SectionTranslation, Tag, TagTranslation
from newsroom.taxonomy.schemas import (
    SectionAdminOut,
    SectionCreate,
    SectionOut,
    SectionTranslationIn,
    SectionUpdate,
    TagAdminOut,
    TagCreate,
    TagOut,
)


class TaxonomyService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_section(self, payload: SectionCreate) -> SectionAdminOut:
        section = Section(
            key=payload.key, parent_id=payload.parent_id, sort_order=payload.sort_order
        )
        section.translations = [_section_translation(item) for item in payload.translations]
        return await self._save_section(section)

    async def update_section(
        self, section_id: uuid.UUID, payload: SectionUpdate
    ) -> SectionAdminOut:
        section = await self.db.get(Section, section_id)
        if section is None:
            raise NotFound("Section not found")
        if payload.parent_id is not None:
            section.parent_id = payload.parent_id
        if payload.sort_order is not None:
            section.sort_order = payload.sort_order
        if payload.is_active is not None:
            section.is_active = payload.is_active
        if payload.translations is not None:
            _replace_section_translations(section, payload.translations)
        return await self._save_section(section)

    async def list_admin_sections(self, q: str | None = None) -> list[SectionAdminOut]:
        stmt = select(Section).order_by(Section.sort_order, Section.key)
        stmt = _match(stmt, q, Section.key, Section.translations, SectionTranslation.name)
        rows = (await self.db.scalars(stmt)).all()
        return [_section_admin(row) for row in rows]

    async def public_sections(self, locale: str) -> list[SectionOut]:
        rows = (
            await self.db.scalars(
                select(Section).where(Section.is_active).order_by(Section.sort_order, Section.key)
            )
        ).all()
        nodes = {row.id: _section_public(row, locale) for row in rows if _translation(row, locale)}
        roots: list[SectionOut] = []
        for row in rows:
            node = nodes.get(row.id)
            if node is None:
                continue
            parent = nodes.get(row.parent_id) if row.parent_id else None
            if parent is None:
                roots.append(node)
            else:
                parent.children.append(node)
        return roots

    async def public_tag(self, locale: str, slug: str) -> TagOut:
        tag = await self.db.scalar(
            select(Tag).where(
                Tag.translations.any(
                    (TagTranslation.locale == locale) & (TagTranslation.slug == slug)
                )
            )
        )
        if tag is None:
            raise NotFound("Tag not found")
        public = tag_public(tag, locale)
        if public is None:
            raise NotFound("Tag not found")
        return public

    async def create_tag(self, payload: TagCreate) -> TagAdminOut:
        tag = Tag(key=payload.key)
        tag.translations = [
            TagTranslation(locale=item.locale, name=item.name, slug=item.slug)
            for item in payload.translations
        ]
        self.db.add(tag)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise Conflict("Tag key or slug already exists") from exc
        return _tag_admin(tag)

    async def merge_tags(
        self, actor: Principal, source_id: uuid.UUID, target_id: uuid.UUID
    ) -> TagAdminOut:
        """Move every story from the source tag onto the target, then remove the source."""
        if source_id == target_id:
            raise Conflict("Choose two different tags")
        source = await self.db.get(Tag, source_id)
        target = await self.db.get(Tag, target_id)
        if source is None or target is None:
            raise NotFound("Tag not found")
        links = list(
            (await self.db.scalars(select(ArticleTag).where(ArticleTag.tag_id == source.id))).all()
        )
        article_ids = [link.article_id for link in links]
        for link in links:
            await self.db.delete(link)
        await self.db.flush()
        for article_id in article_ids:
            existing = await self.db.get(ArticleTag, (article_id, target.id))
            if existing is None:
                self.db.add(ArticleTag(article_id=article_id, tag_id=target.id))
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="tag.merged",
            entity_type="tag",
            entity_id=target.id,
            before={"key": source.key, "id": str(source.id)},
            after={"key": target.key},
        )
        await self.db.delete(source)
        if article_ids:
            published = (
                await self.db.scalars(
                    select(ArticleLocalization.id).where(
                        ArticleLocalization.article_id.in_(article_ids),
                        ArticleLocalization.status == ArticleStatus.PUBLISHED,
                    )
                )
            ).all()
            search = SearchService(self.db)
            for localization_id in published:
                await search.sync(localization_id)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise Conflict("Tag could not be merged") from exc
        return _tag_admin(target)

    async def list_tags(self, paging: PageParams, q: str | None) -> Page[TagAdminOut]:
        stmt = select(Tag).order_by(Tag.key)
        stmt = _match(stmt, q, Tag.key, Tag.translations, TagTranslation.name)
        if paging.cursor:
            stmt = stmt.where(Tag.key > paging.cursor)
        rows = list((await self.db.scalars(stmt.limit(paging.limit + 1))).all())
        next_cursor = None
        if len(rows) > paging.limit:
            rows = rows[: paging.limit]
            next_cursor = rows[-1].key
        return Page(items=[_tag_admin(row) for row in rows], next_cursor=next_cursor)

    async def _save_section(self, section: Section) -> SectionAdminOut:
        self.db.add(section)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise Conflict("Section key or slug already exists") from exc
        return _section_admin(section)


def _section_translation(item: SectionTranslationIn) -> SectionTranslation:
    return SectionTranslation(
        locale=item.locale, name=item.name, slug=item.slug, description=item.description
    )


def _replace_section_translations(section: Section, rows: list[SectionTranslationIn]) -> None:
    """Update translations in place so a kept slug does not collide with itself."""
    incoming = {item.locale: item for item in rows}
    existing = {item.locale: item for item in section.translations}
    for locale, item in existing.items():
        if locale not in incoming:
            section.translations.remove(item)
    for locale, item in incoming.items():
        current = existing.get(locale)
        if current is None:
            section.translations.append(_section_translation(item))
            continue
        current.name = item.name
        current.slug = item.slug
        current.description = item.description


def _translation(section: Section, locale: str) -> SectionTranslation | None:
    return next((item for item in section.translations if item.locale == locale), None)


def _section_admin(section: Section) -> SectionAdminOut:
    return SectionAdminOut(
        id=section.id,
        key=section.key,
        parent_id=section.parent_id,
        sort_order=section.sort_order,
        is_active=section.is_active,
        translations=[
            SectionTranslationIn(
                locale=item.locale, name=item.name, slug=item.slug, description=item.description
            )
            for item in section.translations
        ],
    )


def _section_public(section: Section, locale: str) -> SectionOut | None:
    item = _translation(section, locale)
    if item is None:
        return None
    return SectionOut(
        id=section.id,
        key=section.key,
        parent_id=section.parent_id,
        name=item.name,
        slug=item.slug,
        description=item.description,
    )


def _tag_admin(tag: Tag) -> TagAdminOut:
    from newsroom.taxonomy.schemas import TagTranslationIn

    return TagAdminOut(
        id=tag.id,
        key=tag.key,
        translations=[
            TagTranslationIn(locale=item.locale, name=item.name, slug=item.slug)
            for item in tag.translations
        ],
    )


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _match(stmt, q: str | None, key, translations, name):
    term = (q or "").strip()
    if not term:
        return stmt
    pattern = _like(term)
    named = translations.any(name.ilike(pattern, escape="\\"))
    return stmt.where(or_(key.ilike(pattern, escape="\\"), named))


def tag_public(tag: Tag, locale: str) -> TagOut | None:
    item = next((row for row in tag.translations if row.locale == locale), None)
    if item is None:
        return None
    return TagOut(id=tag.id, key=tag.key, name=item.name, slug=item.slug)
