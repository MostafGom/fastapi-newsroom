import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from newsroom.articles.body import render_body
from newsroom.audit.service import record_event
from newsroom.auth.principal import Principal
from newsroom.authz.permissions import Perm
from newsroom.core.config import get_settings
from newsroom.core.errors import Conflict, NotFound, PermissionDenied
from newsroom.pages.models import Page, PageStatus, PageTranslation
from newsroom.pages.schemas import (
    PageAdminOut,
    PageCreate,
    PageLink,
    PagePublicOut,
    PageTranslationIn,
    PageTranslationOut,
)


class PageService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_admin(self, actor: Principal) -> list[PageAdminOut]:
        self._require(actor)
        rows = (await self.db.scalars(select(Page).order_by(Page.sort_order, Page.key))).all()
        return [_admin(row) for row in rows]

    async def create(self, actor: Principal, payload: PageCreate) -> PageAdminOut:
        self._require(actor)
        page = Page(key=payload.key, sort_order=payload.sort_order, translations=[])
        self.db.add(page)
        await self.db.flush()
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="page.created",
            entity_type="page",
            entity_id=page.id,
            after={"key": page.key, "sort_order": page.sort_order},
        )
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise Conflict("Page key already exists") from exc
        return _admin(page)

    async def save_translation(
        self,
        actor: Principal,
        page_id: uuid.UUID,
        payload: PageTranslationIn,
        *,
        sort_order: int | None = None,
    ) -> PageAdminOut:
        self._require(actor)
        if payload.locale not in get_settings().supported_locales:
            raise NotFound("Locale not found")
        page = await self._page(page_id)
        html = render_body(payload.body)
        current = next((item for item in page.translations if item.locale == payload.locale), None)
        previous = current.status if current is not None else None
        if current is None:
            current = PageTranslation(
                page_id=page.id,
                locale=payload.locale,
                slug=payload.slug,
                title=payload.title,
                body=payload.body,
                body_html=html,
                status=payload.status,
            )
            page.translations.append(current)
        else:
            current.slug = payload.slug
            current.title = payload.title
            current.body = payload.body
            current.body_html = html
            current.status = payload.status
        if sort_order is not None:
            page.sort_order = sort_order
        record_event(
            self.db,
            actor_id=actor.user.id,
            action=_action(previous, payload.status),
            entity_type="page",
            entity_id=page.id,
            after={
                "locale": payload.locale,
                "slug": payload.slug,
                "status": payload.status.value,
            },
        )
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise Conflict("Slug already exists in this language") from exc
        return _admin(page)

    async def delete(self, actor: Principal, page_id: uuid.UUID) -> None:
        self._require(actor)
        page = await self._page(page_id)
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="page.deleted",
            entity_type="page",
            entity_id=page.id,
            before={"key": page.key},
        )
        await self.db.delete(page)
        await self.db.commit()

    async def public_links(self, locale: str) -> list[PageLink]:
        rows = (
            await self.db.scalars(
                select(PageTranslation)
                .join(Page)
                .where(
                    PageTranslation.locale == locale,
                    PageTranslation.status == PageStatus.PUBLISHED,
                )
                .order_by(Page.sort_order, PageTranslation.title)
            )
        ).all()
        return [PageLink(title=row.title, slug=row.slug) for row in rows]

    async def get_public(self, locale: str, slug: str) -> PagePublicOut:
        row = await self.db.scalar(
            select(PageTranslation)
            .join(Page)
            .where(
                PageTranslation.locale == locale,
                PageTranslation.slug == slug,
                PageTranslation.status == PageStatus.PUBLISHED,
            )
            .options(selectinload(PageTranslation.page))
        )
        if row is None or row.page is None:
            raise NotFound("Page not found")
        return PagePublicOut(
            key=row.page.key, title=row.title, slug=row.slug, body_html=row.body_html
        )

    async def _page(self, page_id: uuid.UUID) -> Page:
        page = await self.db.scalar(
            select(Page).where(Page.id == page_id).options(selectinload(Page.translations))
        )
        if page is None:
            raise NotFound("Page not found")
        return page

    def _require(self, actor: Principal) -> None:
        if not actor.grants.has_anywhere(Perm.PAGE_MANAGE):
            raise PermissionDenied("Missing permission: page.manage")


def _action(previous: PageStatus | None, status: PageStatus) -> str:
    if status is PageStatus.PUBLISHED and previous is not PageStatus.PUBLISHED:
        return "page.published"
    if previous is PageStatus.PUBLISHED and status is not PageStatus.PUBLISHED:
        return "page.unpublished"
    return "page.updated"


def _admin(page: Page) -> PageAdminOut:
    return PageAdminOut(
        id=page.id,
        key=page.key,
        sort_order=page.sort_order,
        translations=[
            PageTranslationOut(
                locale=item.locale,
                title=item.title,
                slug=item.slug,
                body=item.body,
                body_html=item.body_html,
                status=item.status,
            )
            for item in page.translations
        ],
    )
