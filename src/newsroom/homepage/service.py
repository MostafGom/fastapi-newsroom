import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from newsroom.articles.models import ArticleLocalization
from newsroom.articles.schemas import ArticleSummaryOut
from newsroom.articles.service import ArticleService, _public_article_options
from newsroom.articles.workflow import ArticleStatus
from newsroom.audit.service import record_event
from newsroom.auth.principal import Principal
from newsroom.authz.permissions import Perm
from newsroom.core.config import get_settings
from newsroom.core.errors import NotFound, PermissionDenied
from newsroom.homepage.models import HomepageSlot


@dataclass(frozen=True, slots=True)
class FrontItem:
    summary: ArticleSummaryOut
    label: str | None


class HomepageService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def replace(
        self,
        actor: Principal,
        locale: str,
        localization_ids: list[uuid.UUID],
        labels: list[str | None] | None = None,
    ) -> None:
        if not actor.grants.has_anywhere(Perm.ARTICLE_PUBLISH):
            raise PermissionDenied("Missing permission: article.publish")
        if locale not in get_settings().supported_locales:
            raise NotFound("Locale not found")
        labels = labels or []
        chosen: list[tuple[uuid.UUID, str | None]] = []
        seen: set[uuid.UUID] = set()
        for index, localization_id in enumerate(localization_ids):
            if localization_id in seen:
                continue
            seen.add(localization_id)
            raw = labels[index] if index < len(labels) else None
            label = raw.strip()[:120] if isinstance(raw, str) and raw.strip() else None
            chosen.append((localization_id, label))
        if len(chosen) > 12:
            chosen = chosen[:12]
        unique = [item[0] for item in chosen]
        if unique:
            rows = list(
                (
                    await self.db.scalars(
                        select(ArticleLocalization).where(ArticleLocalization.id.in_(unique))
                    )
                ).all()
            )
            found = {row.id: row for row in rows}
            for localization_id in unique:
                row = found.get(localization_id)
                if row is None or row.locale != locale or row.status is not ArticleStatus.PUBLISHED:
                    raise NotFound("Published story not found")
        await self.db.execute(delete(HomepageSlot).where(HomepageSlot.locale == locale))
        for position, (localization_id, label) in enumerate(chosen, start=1):
            self.db.add(
                HomepageSlot(
                    locale=locale,
                    position=position,
                    localization_id=localization_id,
                    label=label,
                )
            )
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="homepage.updated",
            entity_type="homepage",
            entity_id=locale,
            after={"count": len(unique)},
        )
        await self.db.commit()

    async def public_stories(self, locale: str) -> list[FrontItem] | None:
        slots = list(
            (
                await self.db.scalars(
                    select(HomepageSlot)
                    .where(HomepageSlot.locale == locale)
                    .order_by(HomepageSlot.position)
                )
            ).all()
        )
        if not slots:
            return None
        ids = [slot.localization_id for slot in slots]
        rows = list(
            (
                await self.db.scalars(
                    select(ArticleLocalization)
                    .where(ArticleLocalization.id.in_(ids))
                    .options(*_public_article_options(selectinload(ArticleLocalization.article)))
                )
            ).all()
        )
        by_id = {row.id: row for row in rows}
        articles = ArticleService(self.db)
        items: list[FrontItem] = []
        for slot in slots:
            row = by_id.get(slot.localization_id)
            if row is not None and row.status is ArticleStatus.PUBLISHED:
                items.append(FrontItem(articles._summary(row, locale), slot.label))
        return items
