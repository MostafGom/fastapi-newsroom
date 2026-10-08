"""Guest and agency bylines. Staff authors are created with the user account."""

import uuid

from pydantic import Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.articles.models import ArticleAuthor, Author, AuthorKind, AuthorTranslation
from newsroom.audit.service import record_event
from newsroom.auth.principal import Principal
from newsroom.authz.permissions import Perm
from newsroom.core.errors import Conflict, NotFound, PermissionDenied
from newsroom.core.schemas import Schema, Slug


class AuthorTranslationIn(Schema):
    locale: str = Field(max_length=10)
    display_name: str = Field(min_length=1, max_length=120)
    slug: Slug
    bio: str | None = Field(default=None, max_length=2000)


class AuthorCreate(Schema):
    kind: AuthorKind
    key: str = Field(pattern=r"^[a-z0-9_-]+$", max_length=64)
    translations: list[AuthorTranslationIn] = Field(min_length=1)


class AuthorOut(Schema):
    id: uuid.UUID
    kind: AuthorKind
    key: str
    display_name: str


class AuthorService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_bylines(self, q: str | None = None) -> list[AuthorOut]:
        stmt = select(Author).order_by(Author.key)
        term = (q or "").strip()
        if term:
            pattern = _like(term)
            named = Author.translations.any(
                AuthorTranslation.display_name.ilike(pattern, escape="\\")
            )
            stmt = stmt.where(or_(Author.key.ilike(pattern, escape="\\"), named))
        rows = (await self.db.scalars(stmt)).all()
        return [_out(row) for row in rows]

    async def create(self, actor: Principal, payload: AuthorCreate) -> AuthorOut:
        self._require(actor)
        if payload.kind is AuthorKind.STAFF:
            raise Conflict("Staff bylines are created with the staff account")
        author = Author(id=uuid.uuid7(), kind=payload.kind, key=payload.key)
        author.translations = [
            AuthorTranslation(
                locale=item.locale,
                display_name=item.display_name,
                slug=item.slug,
                bio=item.bio,
            )
            for item in payload.translations
        ]
        self.db.add(author)
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="author.created",
            entity_type="author",
            entity_id=author.id,
            after={"kind": payload.kind.value, "key": payload.key},
        )
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise Conflict("Author key or slug already exists") from exc
        return _out(author)

    async def delete(self, actor: Principal, author_id: uuid.UUID) -> None:
        self._require(actor)
        author = await self.db.get(Author, author_id)
        if author is None:
            raise NotFound("Author not found")
        if author.kind is AuthorKind.STAFF:
            raise Conflict("A staff byline is removed with the staff account")
        used = await self.db.scalar(
            select(ArticleAuthor.article_id).where(ArticleAuthor.author_id == author.id).limit(1)
        )
        if used is not None:
            raise Conflict("This byline is on a story. Change the story before deleting it")
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="author.deleted",
            entity_type="author",
            entity_id=author.id,
            before={"key": author.key, "kind": author.kind.value},
        )
        await self.db.delete(author)
        await self.db.commit()

    @staticmethod
    def _require(actor: Principal) -> None:
        if actor.grants.has_anywhere(Perm.ARTICLE_CREATE) or actor.grants.has_anywhere(
            Perm.ARTICLE_EDIT
        ):
            return
        raise PermissionDenied("Missing permission: article.create")


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _out(author: Author) -> AuthorOut:
    name = author.key
    if author.translations:
        name = author.translations[0].display_name
    return AuthorOut(id=author.id, kind=author.kind, key=author.key, display_name=name)
