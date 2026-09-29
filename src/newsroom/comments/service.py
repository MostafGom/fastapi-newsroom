import uuid

import nh3
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from newsroom.articles.models import Article, ArticleLocalization
from newsroom.articles.workflow import ArticleStatus
from newsroom.audit.service import record_event
from newsroom.auth.principal import Principal
from newsroom.auth.service import utcnow
from newsroom.authz.permissions import Perm
from newsroom.comments.models import Comment
from newsroom.comments.schemas import CommentOut
from newsroom.core.errors import Conflict, NotFound, PermissionDenied


class CommentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_for_slug(
        self, locale: str, slug: str, reader_id: uuid.UUID | None
    ) -> list[CommentOut]:
        localization = await self._published(locale, slug)
        return await self.list_public(localization.id, reader_id)

    async def add_for_slug(
        self, reader: Principal, locale: str, slug: str, body: str
    ) -> CommentOut:
        localization = await self._published(locale, slug)
        return await self.add(reader, localization.id, body)

    async def _published(self, locale: str, slug: str) -> ArticleLocalization:
        localization = await self.db.scalar(
            select(ArticleLocalization).where(
                ArticleLocalization.locale == locale,
                ArticleLocalization.slug == slug,
                ArticleLocalization.status == ArticleStatus.PUBLISHED,
            )
        )
        if localization is None:
            raise NotFound("Article not found")
        return localization

    async def list_public(
        self, localization_id: uuid.UUID, reader_id: uuid.UUID | None
    ) -> list[CommentOut]:
        rows = list(
            (
                await self.db.scalars(
                    select(Comment)
                    .where(
                        Comment.localization_id == localization_id,
                        Comment.hidden_at.is_(None),
                    )
                    .options(selectinload(Comment.user))
                    .order_by(Comment.created_at)
                )
            ).all()
        )
        return [_out(row, reader_id) for row in rows]

    async def add(self, reader: Principal, localization_id: uuid.UUID, body: str) -> CommentOut:
        localization = await self.db.get(ArticleLocalization, localization_id)
        if localization is None or localization.status is not ArticleStatus.PUBLISHED:
            raise NotFound("Article not found")
        text = nh3.clean(body, tags=set()).strip()
        if not text:
            raise Conflict("Comment is empty")
        if len(text) > 2000:
            raise Conflict("Comment is too long")
        comment = Comment(
            id=uuid.uuid7(),
            localization_id=localization.id,
            user_id=reader.user.id,
            body=text,
            created_at=utcnow(),
        )
        self.db.add(comment)
        record_event(
            self.db,
            actor_id=reader.user.id,
            action="comment.created",
            entity_type="comment",
            entity_id=comment.id,
            after={"localization_id": str(localization.id)},
        )
        await self.db.commit()
        comment.user = reader.user
        return _out(comment, reader.user.id)

    async def hide_by_staff(self, actor: Principal, comment_id: uuid.UUID) -> None:
        comment = await self._visible(comment_id)
        localization = await self.db.get(ArticleLocalization, comment.localization_id)
        article = await self.db.get(Article, localization.article_id) if localization else None
        if article is None or not actor.grants.has(
            Perm.ARTICLE_EDIT, section_id=article.section_id
        ):
            raise PermissionDenied("You cannot remove this comment")
        await self._hide(comment, actor.user.id)

    async def hide(self, reader: Principal, comment_id: uuid.UUID) -> None:
        comment = await self._visible(comment_id)
        if comment.user_id != reader.user.id:
            raise PermissionDenied("You can only remove your own comment")
        await self._hide(comment, reader.user.id)

    async def _visible(self, comment_id: uuid.UUID) -> Comment:
        comment = await self.db.get(Comment, comment_id)
        if comment is None or comment.hidden_at is not None:
            raise NotFound("Comment not found")
        return comment

    async def _hide(self, comment: Comment, actor_id: uuid.UUID) -> None:
        comment.hidden_at = utcnow()
        record_event(
            self.db,
            actor_id=actor_id,
            action="comment.hidden",
            entity_type="comment",
            entity_id=comment.id,
        )
        await self.db.commit()


def _out(comment: Comment, reader_id: uuid.UUID | None) -> CommentOut:
    user = comment.user
    name = user.display_name or user.email
    return CommentOut(
        id=comment.id,
        localization_id=comment.localization_id,
        author_name=name,
        body=comment.body,
        created_at=comment.created_at,
        mine=reader_id is not None and comment.user_id == reader_id,
    )
