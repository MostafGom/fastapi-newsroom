import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from newsroom.articles.body import InvalidBody, referenced_media, render_body
from newsroom.articles.models import (
    Article,
    ArticleAuthor,
    ArticleLocalization,
    ArticleRevision,
    ArticleTag,
    Author,
    Bookmark,
    Correction,
    SlugRedirect,
)
from newsroom.articles.schemas import (
    AlternateOut,
    ArticleAdminOut,
    ArticleCreate,
    ArticleOut,
    ArticleSummaryOut,
    ArticleUpdate,
    BylineOut,
    CorrectionCreate,
    CorrectionOut,
    FieldDiff,
    HistoryEntryKind,
    HistoryEntryOut,
    LocalizationCreate,
    LocalizationOut,
    LocalizationSummaryOut,
    RestoreRequest,
    RevisionContent,
    RevisionCreate,
    RevisionDiffOut,
    RevisionKind,
    RevisionOut,
    RevisionSummaryOut,
    SectionRefOut,
    SlugChange,
    TransitionRequest,
)
from newsroom.articles.workflow import (
    EDITABLE_BY_OWNER,
    ArticleAction,
    ArticleStatus,
    ReasonRequired,
    available_actions,
    resolve_transition,
)
from newsroom.audit.models import AuditEvent
from newsroom.audit.service import record_event
from newsroom.auth.principal import Principal
from newsroom.authz.permissions import Perm
from newsroom.core.errors import Conflict, Gone, NotFound, PermissionDenied
from newsroom.core.schemas import Page, PageParams, decode_keyset, encode_cursor
from newsroom.media.models import MediaAsset
from newsroom.search.service import SearchService
from newsroom.taxonomy.models import Section, SectionTranslation, Tag, TagTranslation
from newsroom.taxonomy.service import tag_public
from newsroom.users.models import UserKind

AUTOSAVE_WINDOW = timedelta(minutes=5)


class RevisionConflict(Conflict):
    code = "revision_conflict"


class VersionConflict(Conflict):
    code = "version_conflict"


class LegalHoldActive(Conflict):
    code = "legal_hold"


@dataclass(slots=True)
class PublicLookup:
    article: ArticleOut | None = None
    redirect_slug: str | None = None
    gone: bool = False


def utcnow() -> datetime:
    return datetime.now(UTC)


def _public_article_options(article_loader):
    """Eager-load everything a public card or page reads. Async sessions cannot lazy-load."""
    return (
        article_loader.selectinload(Article.section).selectinload(Section.translations),
        article_loader.selectinload(Article.article_authors)
        .selectinload(ArticleAuthor.author)
        .selectinload(Author.translations),
        article_loader.selectinload(Article.article_tags)
        .selectinload(ArticleTag.tag)
        .selectinload(Tag.translations),
        article_loader.selectinload(Article.localizations).selectinload(
            ArticleLocalization.revisions
        ),
        article_loader.selectinload(Article.localizations).selectinload(
            ArticleLocalization.corrections
        ),
    )


class ArticleService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, actor: Principal, payload: ArticleCreate) -> ArticleAdminOut:
        self._require(actor, Perm.ARTICLE_CREATE, payload.section_id)
        article = Article(
            section_id=payload.section_id,
            article_type=payload.article_type,
            lead_media_id=payload.lead_media_id,
            is_breaking=payload.is_breaking,
            created_by=actor.user.id,
        )
        article.article_authors = [
            ArticleAuthor(author_id=author_id, position=index)
            for index, author_id in enumerate(payload.author_ids)
        ]
        article.article_tags = [ArticleTag(tag_id=tag_id) for tag_id in payload.tag_ids]
        self.db.add(article)
        await self.db.flush()
        set_committed_value(article, "localizations", [])
        await self._add_localization(article, actor, payload.locale, payload.slug, payload.content)
        await self._commit_article()
        return await self._admin_out(article.id)

    async def add_localization(
        self, actor: Principal, article_id: uuid.UUID, payload: LocalizationCreate
    ) -> LocalizationOut:
        article = await self._article(article_id)
        self._require(actor, Perm.ARTICLE_CREATE, article.section_id)
        localization = await self._add_localization(
            article, actor, payload.locale, payload.slug, payload.content
        )
        await self._commit_article()
        return self._localization_out(localization)

    async def update_article(
        self, actor: Principal, article_id: uuid.UUID, payload: ArticleUpdate
    ) -> ArticleAdminOut:
        article = await self._article(article_id)
        self._require_edit(actor, article, None)
        if payload.lock_version != self._lock(article):
            raise VersionConflict("Article was updated by someone else")
        if payload.section_id is not None:
            self._require(actor, Perm.ARTICLE_EDIT, payload.section_id)
            article.section_id = payload.section_id
        if payload.article_type is not None:
            article.article_type = payload.article_type
        if payload.is_breaking is not None:
            article.is_breaking = payload.is_breaking
        if payload.lead_media_id is not None:
            article.lead_media_id = payload.lead_media_id
        if payload.author_ids is not None:
            article.article_authors.clear()
            article.article_authors.extend(
                ArticleAuthor(author_id=author_id, position=index)
                for index, author_id in enumerate(payload.author_ids)
            )
        if payload.tag_ids is not None:
            article.article_tags.clear()
            article.article_tags.extend(ArticleTag(tag_id=tag_id) for tag_id in payload.tag_ids)
        await self._commit_article()
        return await self._admin_out(article.id)

    async def save_revision(
        self, actor: Principal, localization_id: uuid.UUID, payload: RevisionCreate
    ) -> RevisionOut:
        localization = await self._localization(localization_id)
        self._require_edit(actor, localization.article, localization)
        if payload.kind is RevisionKind.AUTOSAVE:
            await self._require_media(payload.content.body)
            coalesced = self._coalesce_autosave(localization, actor, payload)
            if coalesced is not None:
                await self._commit_article()
                return self._revision_out(coalesced, localization)
        if localization.current_revision_id != payload.base_revision_id:
            raise RevisionConflict("Revision is stale")
        await self._require_media(payload.content.body)
        revision = self._new_revision(
            localization,
            actor,
            payload.content,
            payload.kind,
            payload.change_note,
            parent_id=payload.base_revision_id,
        )
        await self.db.flush()
        localization.current_revision_id = revision.id
        if payload.kind is RevisionKind.MANUAL and self._writer_proposal(actor, localization):
            localization.update_requested_at = utcnow()
        localization.lock_version += 1
        await self._commit_article()
        return self._revision_out(revision, localization)

    async def delete_localization(self, actor: Principal, localization_id: uuid.UUID) -> None:
        """Soft-delete a draft that has never been published. The row stays for the audit trail."""
        localization = await self._localization(localization_id)
        await self.transition(
            actor,
            localization_id,
            TransitionRequest(action=ArticleAction.DELETE, lock_version=localization.lock_version),
        )

    async def set_legal_hold(
        self, actor: Principal, localization_id: uuid.UUID, reason: str
    ) -> None:
        """Block schedule, publish, and republish until counsel is recorded. Not a status."""
        localization = await self._localization(localization_id)
        self._require(actor, Perm.ARTICLE_REVIEW, localization.article.section_id)
        self._require_reason(reason, "hold a story")
        if localization.legal_hold:
            raise Conflict("This story is already on legal hold")
        if localization.status is ArticleStatus.ARCHIVED:
            raise Conflict("An archived story cannot be put on legal hold")
        localization.legal_hold = True
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="article.legal_hold",
            entity_type="article_localization",
            entity_id=localization.id,
            before={"legal_hold": False},
            after={"legal_hold": True},
            reason=reason.strip(),
        )
        await self.db.commit()

    async def clear_legal_hold(
        self, actor: Principal, localization_id: uuid.UUID, reason: str
    ) -> None:
        """Record that counsel signed off. The editor is the user of the app, not counsel."""
        localization = await self._localization(localization_id)
        self._require(actor, Perm.ARTICLE_CLEAR_LEGAL, localization.article.section_id)
        self._require_reason(reason, "clear a legal hold")
        if not localization.legal_hold:
            raise Conflict("This story is not on legal hold")
        localization.legal_hold = False
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="article.clear_legal",
            entity_type="article_localization",
            entity_id=localization.id,
            before={"legal_hold": True},
            after={"legal_hold": False},
            reason=reason.strip(),
        )
        await self.db.commit()

    async def purge(self, actor: Principal, localization_id: uuid.UUID, reason: str) -> None:
        """Hard-remove one language edition. The audit row keeps the identifiers."""
        if not actor.grants.has_anywhere(Perm.ARTICLE_PURGE):
            raise PermissionDenied("Missing permission: article.purge")
        self._require_reason(reason, "purge a story")
        localization = await self._localization(localization_id)
        article = localization.article
        current = self._revision(localization, localization.current_revision_id)
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="article.purge",
            entity_type="article_localization",
            entity_id=localization.id,
            before={
                "article_id": str(article.id),
                "locale": localization.locale,
                "slug": localization.slug,
                "title": current.title if current else "",
                "status": localization.status.value,
            },
            reason=reason.strip(),
        )
        await self.db.flush()
        article_id = article.id
        localization.current_revision_id = None
        localization.published_revision_id = None
        await self.db.flush()
        for revision in list(localization.revisions):
            revision.parent_revision_id = None
            revision.restored_from_id = None
        await self.db.flush()
        for revision in list(localization.revisions):
            await self.db.delete(revision)
        localization.revisions.clear()
        if localization in article.localizations:
            article.localizations.remove(localization)
        await self.db.delete(localization)
        await self.db.flush()
        left = await self.db.scalar(
            select(func.count())
            .select_from(ArticleLocalization)
            .where(ArticleLocalization.article_id == article_id)
        )
        if not left:
            await self.db.delete(article)
        await self._commit_article()

    async def list_revisions(
        self, actor: Principal, localization_id: uuid.UUID, paging: PageParams
    ) -> Page[RevisionSummaryOut]:
        localization = await self._readable(actor, localization_id)
        ordered = sorted(localization.revisions, key=lambda item: item.revision_no, reverse=True)
        if paging.cursor:
            try:
                before = int(paging.cursor)
            except ValueError as exc:
                raise Conflict("Invalid cursor") from exc
            ordered = [item for item in ordered if item.revision_no < before]
        page = ordered[: paging.limit]
        next_cursor = str(page[-1].revision_no) if len(ordered) > paging.limit else None
        return Page(
            items=[self._revision_summary(item, localization) for item in page],
            next_cursor=next_cursor,
        )

    async def get_revision(
        self, actor: Principal, localization_id: uuid.UUID, revision_id: uuid.UUID
    ) -> RevisionOut:
        localization = await self._readable(actor, localization_id)
        revision = self._revision(localization, revision_id)
        if revision is None:
            raise NotFound("Revision not found")
        return self._revision_out(revision, localization)

    async def diff_revisions(
        self,
        actor: Principal,
        localization_id: uuid.UUID,
        from_id: uuid.UUID,
        to_id: uuid.UUID,
    ) -> RevisionDiffOut:
        localization = await self._readable(actor, localization_id)
        older = self._revision(localization, from_id)
        newer = self._revision(localization, to_id)
        if older is None or newer is None:
            raise NotFound("Revision not found")
        return RevisionDiffOut(
            from_revision_id=older.id,
            to_revision_id=newer.id,
            fields=self._field_diffs(older, newer),
        )

    async def restore_revision(
        self,
        actor: Principal,
        localization_id: uuid.UUID,
        revision_id: uuid.UUID,
        payload: RestoreRequest,
    ) -> RevisionOut:
        localization = await self._localization(localization_id)
        article = localization.article
        self._require(actor, Perm.ARTICLE_RESTORE_REVISION, article.section_id)
        if localization.status is ArticleStatus.ARCHIVED:
            raise PermissionDenied("Archived stories cannot be edited")
        source = self._revision(localization, revision_id)
        if source is None:
            raise NotFound("Revision not found")
        if localization.current_revision_id != payload.base_revision_id:
            raise RevisionConflict("Revision is stale")
        if source.id == localization.current_revision_id:
            raise Conflict("That revision is already the working copy")
        content = RevisionContent(
            title=source.title,
            subtitle=source.subtitle,
            excerpt=source.excerpt,
            body=source.body,
            seo_title=source.seo_title,
            seo_description=source.seo_description,
        )
        await self._require_media(content.body)
        revision = self._new_revision(
            localization,
            actor,
            content,
            RevisionKind.RESTORE,
            payload.change_note,
            parent_id=localization.current_revision_id,
        )
        revision.restored_from_id = source.id
        await self.db.flush()
        localization.current_revision_id = revision.id
        localization.lock_version += 1
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="article.revision_restored",
            entity_type="article_localization",
            entity_id=localization.id,
            after={"revision_id": str(revision.id), "restored_from_id": str(source.id)},
            reason=payload.change_note,
        )
        await self._commit_article()
        return self._revision_out(revision, localization)

    async def transition(
        self, actor: Principal, localization_id: uuid.UUID, payload
    ) -> LocalizationOut:
        localization = await self._localization(localization_id)
        article = localization.article
        if localization.lock_version != payload.lock_version:
            raise VersionConflict("Article was updated by someone else")
        edge = resolve_transition(
            localization.status,
            payload.action,
            reason=payload.reason,
            ever_published=localization.first_published_at is not None,
        )
        self._require_transition(actor, article, edge)
        if localization.legal_hold and payload.action in {
            ArticleAction.PUBLISH,
            ArticleAction.SCHEDULE,
            ArticleAction.REPUBLISH,
        }:
            raise LegalHoldActive("Going live is blocked until legal hold is cleared")
        if payload.action is ArticleAction.SCHEDULE and (
            payload.publish_at is None or payload.publish_at <= utcnow()
        ):
            raise Conflict("publish_at must be in the future")
        if (
            payload.action is ArticleAction.SCHEDULE
            and payload.unpublish_at is not None
            and (payload.publish_at is None or payload.unpublish_at <= payload.publish_at)
        ):
            raise Conflict("unpublish_at must be after publish_at")
        if payload.action is ArticleAction.UNPUBLISH and payload.takedown_reason is None:
            raise Conflict("A takedown reason code is required")
        before = localization.status.value
        self._apply_transition(localization, payload)
        record_event(
            self.db,
            actor_id=actor.user.id,
            action=f"article.{payload.action.value}",
            entity_type="article_localization",
            entity_id=localization.id,
            before={"status": before},
            after={
                "status": localization.status.value,
                "takedown_reason": payload.takedown_reason.value
                if payload.takedown_reason
                else None,
            },
            reason=payload.reason,
        )
        if payload.action in {
            ArticleAction.PUBLISH,
            ArticleAction.REPUBLISH,
            ArticleAction.PUBLISH_UPDATE,
            ArticleAction.UNPUBLISH,
        }:
            await self._sync_search(localization.id)
        await self._commit_article()
        return self._localization_out(localization)

    async def add_correction(
        self, actor: Principal, localization_id: uuid.UUID, payload: CorrectionCreate
    ) -> CorrectionOut:
        localization = await self._localization(localization_id)
        self._require(actor, Perm.ARTICLE_CORRECT, localization.article.section_id)
        if localization.first_published_at is None:
            raise Conflict("A public note can only be added after the story has been published")
        correction = Correction(
            localization_id=localization.id,
            kind=payload.kind,
            text=payload.text,
            created_by=actor.user.id,
        )
        localization.corrections.append(correction)
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="article.corrected",
            entity_type="article_localization",
            entity_id=localization.id,
            after={"kind": payload.kind.value},
        )
        await self.db.commit()
        return CorrectionOut.model_validate(correction)

    async def change_slug(
        self, actor: Principal, localization_id: uuid.UUID, payload: SlugChange
    ) -> LocalizationOut:
        """Point the localization at a new slug. A story that has been live keeps the old URL."""
        localization = await self._localization(localization_id)
        article = localization.article
        if localization.first_published_at is not None:
            self._require(actor, Perm.ARTICLE_EDIT, article.section_id)
        else:
            self._require_edit(actor, article, localization)
        new_slug = payload.slug
        if new_slug == localization.slug:
            return self._localization_out(localization)
        reclaim = await self.db.get(
            SlugRedirect, {"locale": localization.locale, "old_slug": new_slug}
        )
        if reclaim is not None:
            if reclaim.localization_id != localization.id:
                raise Conflict("Slug is already in use")
            await self.db.delete(reclaim)
            await self.db.flush()
        old_slug = localization.slug
        if localization.first_published_at is not None:
            self.db.add(
                SlugRedirect(
                    locale=localization.locale,
                    old_slug=old_slug,
                    localization_id=localization.id,
                )
            )
        localization.slug = new_slug
        localization.lock_version += 1
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="article.slug_changed",
            entity_type="article_localization",
            entity_id=localization.id,
            before={"slug": old_slug},
            after={"slug": new_slug},
        )
        if localization.status is ArticleStatus.PUBLISHED:
            await self._sync_search(localization.id)
        await self._commit_article()
        return self._localization_out(localization)

    async def list_admin(
        self,
        actor: Principal,
        paging: PageParams,
        *,
        status: ArticleStatus | None,
        locale: str | None,
        section_id: uuid.UUID | None,
    ) -> Page[ArticleAdminOut]:
        if actor.user.kind is not UserKind.STAFF:
            return Page(items=[], next_cursor=None)
        visible = ArticleLocalization.deleted_at.is_(None)
        if status is not None:
            visible = and_(visible, ArticleLocalization.status == status)
        if locale is not None:
            visible = and_(visible, ArticleLocalization.locale == locale)
        stmt = (
            select(Article)
            .where(Article.localizations.any(visible))
            .order_by(Article.created_at.desc(), Article.id.desc())
            .options(
                selectinload(Article.localizations).selectinload(ArticleLocalization.revisions),
                selectinload(Article.article_authors),
                selectinload(Article.article_tags),
            )
        )
        if section_id is not None:
            stmt = stmt.where(Article.section_id == section_id)
        scope = actor.grants.sections_with(Perm.ARTICLE_READ)
        if scope is not None:
            own = Article.created_by == actor.user.id
            stmt = stmt.where(or_(Article.section_id.in_(scope), own) if scope else own)
        if paging.cursor:
            created_at, row_id = decode_keyset(paging.cursor, "created_at")
            stmt = stmt.where(tuple_(Article.created_at, Article.id) < tuple_(created_at, row_id))
        rows = list((await self.db.scalars(stmt.limit(paging.limit + 1))).all())
        next_cursor = None
        if len(rows) > paging.limit:
            rows = rows[: paging.limit]
            last = rows[-1]
            next_cursor = encode_cursor(
                {"created_at": last.created_at.isoformat(), "id": str(last.id)}
            )
        items = []
        for article in rows:
            if not self._can_read(actor, article):
                continue
            out = self._admin_from(article)
            if not out.localizations:
                continue
            if status is not None or locale is not None:
                out.localizations = [
                    item
                    for item in out.localizations
                    if (status is None or item.status is status)
                    and (locale is None or item.locale == locale)
                ]
                if not out.localizations:
                    continue
            items.append(out)
        return Page(items=items, next_cursor=next_cursor)

    async def get_admin(self, actor: Principal, article_id: uuid.UUID) -> ArticleAdminOut:
        article = await self._article(article_id)
        if not self._can_read(actor, article):
            raise PermissionDenied("You cannot view this article")
        return self._admin_from(article)

    async def get_localization(
        self, actor: Principal, localization_id: uuid.UUID
    ) -> LocalizationOut:
        localization = await self._localization(localization_id)
        if not self._can_read(actor, localization.article):
            raise PermissionDenied("You cannot view this article")
        return self._localization_out(localization)

    async def list_public(
        self, locale: str, paging: PageParams, *, section_slug: str | None, tag_slug: str | None
    ) -> Page[ArticleSummaryOut]:
        stmt = (
            select(ArticleLocalization)
            .where(
                ArticleLocalization.locale == locale,
                ArticleLocalization.status == ArticleStatus.PUBLISHED,
                ArticleLocalization.deleted_at.is_(None),
                ArticleLocalization.published_at.is_not(None),
            )
            .order_by(ArticleLocalization.published_at.desc(), ArticleLocalization.id.desc())
            .options(*_public_article_options(selectinload(ArticleLocalization.article)))
        )
        if section_slug is not None:
            stmt = stmt.where(
                ArticleLocalization.article.has(
                    Article.section.has(
                        Section.translations.any(
                            (SectionTranslation.locale == locale)
                            & (SectionTranslation.slug == section_slug)
                        )
                    )
                )
            )
        if tag_slug is not None:
            stmt = stmt.where(
                ArticleLocalization.article.has(
                    Article.article_tags.any(
                        ArticleTag.tag.has(
                            Tag.translations.any(
                                (TagTranslation.locale == locale)
                                & (TagTranslation.slug == tag_slug)
                            )
                        )
                    )
                )
            )
        if paging.cursor:
            published_at, row_id = decode_keyset(paging.cursor, "published_at")
            stmt = stmt.where(
                tuple_(ArticleLocalization.published_at, ArticleLocalization.id)
                < tuple_(published_at, row_id)
            )
        rows = list((await self.db.scalars(stmt.limit(paging.limit + 1))).all())
        next_cursor = None
        if len(rows) > paging.limit:
            rows = rows[: paging.limit]
            last = rows[-1]
            published_at = last.published_at
            if published_at is not None:
                next_cursor = encode_cursor(
                    {"published_at": published_at.isoformat(), "id": str(last.id)}
                )
        items = [self._summary(row, locale) for row in rows]
        return Page(items=items, next_cursor=next_cursor)

    async def get_public(self, locale: str, slug: str) -> PublicLookup:
        localization = await self.db.scalar(
            select(ArticleLocalization)
            .where(ArticleLocalization.locale == locale, ArticleLocalization.slug == slug)
            .options(*_public_article_options(selectinload(ArticleLocalization.article)))
        )
        if localization is None:
            redirect = await self.db.get(SlugRedirect, {"locale": locale, "old_slug": slug})
            if redirect is not None:
                target = await self.db.get(ArticleLocalization, redirect.localization_id)
                if target is not None:
                    return PublicLookup(redirect_slug=target.slug)
            raise NotFound("Article not found")
        if localization.status is ArticleStatus.UNPUBLISHED:
            raise Gone("This story was taken down")
        if (
            localization.status is not ArticleStatus.PUBLISHED
            or localization.published_revision_id is None
        ):
            raise NotFound("Article not found")
        return PublicLookup(article=self._public_out(localization, locale))

    async def publish_due(self) -> int:
        """Publish due rows one transaction at a time so a replica can skip a locked row."""
        count = 0
        while count < 50:
            localization = await self.db.scalar(
                select(ArticleLocalization)
                .where(
                    ArticleLocalization.status == ArticleStatus.SCHEDULED,
                    ArticleLocalization.publish_at <= utcnow(),
                    ArticleLocalization.legal_hold.is_(False),
                )
                .order_by(ArticleLocalization.publish_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if localization is None:
                return count
            self._apply_transition(localization, _Due(ArticleAction.PUBLISH))
            record_event(
                self.db,
                actor_id=None,
                action=f"article.{ArticleAction.PUBLISH.value}",
                entity_type="article_localization",
                entity_id=localization.id,
                after={"status": localization.status.value, "via": "scheduler"},
            )
            await self._sync_search(localization.id)
            await self.db.commit()
            count += 1
        return count

    async def unpublish_due(self) -> int:
        count = 0
        while count < 50:
            now = utcnow()
            localization = await self.db.scalar(
                select(ArticleLocalization)
                .where(
                    ArticleLocalization.status == ArticleStatus.PUBLISHED,
                    ArticleLocalization.unpublish_at.is_not(None),
                    ArticleLocalization.unpublish_at <= now,
                )
                .order_by(ArticleLocalization.unpublish_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if localization is None:
                return count
            localization.status = ArticleStatus.UNPUBLISHED
            localization.unpublish_at = None
            localization.lock_version += 1
            record_event(
                self.db,
                actor_id=None,
                action=f"article.{ArticleAction.UNPUBLISH.value}",
                entity_type="article_localization",
                entity_id=localization.id,
                after={"status": "unpublished", "via": "scheduler"},
                reason="Embargo expired",
            )
            await self._sync_search(localization.id)
            await self.db.commit()
            count += 1
        return count

    async def set_lead(
        self, actor: Principal, article_id: uuid.UUID, media_id: uuid.UUID | None
    ) -> None:
        article = await self._article(article_id)
        self._require_edit(actor, article, None)
        if media_id is not None and await self.db.get(MediaAsset, media_id) is None:
            raise NotFound("Media not found")
        article.lead_media_id = media_id
        record_event(
            self.db,
            actor_id=actor.user.id,
            action="article.lead_set",
            entity_type="article",
            entity_id=article.id,
            after={"lead_media_id": str(media_id) if media_id else None},
        )
        await self._commit_article()

    async def _require_media(self, document: dict) -> None:
        needed = referenced_media(document)
        if not needed:
            return
        found = set(
            (await self.db.scalars(select(MediaAsset.id).where(MediaAsset.id.in_(needed)))).all()
        )
        if found != needed:
            raise InvalidBody("An image points at a media file that does not exist")

    async def _sync_search(self, localization_id: uuid.UUID) -> None:
        await self._flush_article()
        await SearchService(self.db).sync(localization_id)

    async def bookmark(self, user_id: uuid.UUID, article_id: uuid.UUID) -> None:
        article = await self.db.get(Article, article_id)
        if article is None:
            raise NotFound("Article not found")
        self.db.add(Bookmark(user_id=user_id, article_id=article_id))
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()

    async def unbookmark(self, user_id: uuid.UUID, article_id: uuid.UUID) -> None:
        row = await self.db.get(Bookmark, {"user_id": user_id, "article_id": article_id})
        if row is not None:
            await self.db.delete(row)
            await self.db.commit()

    async def list_bookmarks(self, user_id: uuid.UUID, locale: str) -> list[ArticleSummaryOut]:
        rows = (
            await self.db.scalars(
                select(Bookmark)
                .where(Bookmark.user_id == user_id)
                .order_by(Bookmark.created_at.desc())
                .options(*_public_article_options(selectinload(Bookmark.article)))
            )
        ).all()
        items: list[ArticleSummaryOut] = []
        for row in rows:
            localization = next(
                (
                    item
                    for item in row.article.localizations
                    if item.locale == locale and item.status is ArticleStatus.PUBLISHED
                ),
                None,
            )
            if localization is None:
                localization = next(
                    (
                        item
                        for item in row.article.localizations
                        if item.status is ArticleStatus.PUBLISHED
                    ),
                    None,
                )
            if localization is not None:
                items.append(self._summary(localization, localization.locale))
        return items

    async def history(self, actor: Principal, localization_id: uuid.UUID) -> list[HistoryEntryOut]:
        localization = await self._localization(localization_id)
        if not self._can_read(actor, localization.article):
            raise PermissionDenied("You cannot view this article")
        entries = [
            HistoryEntryOut(
                kind=HistoryEntryKind.REVISION,
                occurred_at=revision.created_at,
                actor_id=revision.created_by,
                action=f"revision.{revision.kind.value}",
                revision_id=revision.id,
                reason=revision.change_note,
            )
            for revision in localization.revisions
        ]
        events = (
            await self.db.scalars(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "article_localization",
                    AuditEvent.entity_id == str(localization.id),
                )
            )
        ).all()
        entries.extend(
            HistoryEntryOut(
                kind=HistoryEntryKind.EVENT,
                occurred_at=event.occurred_at,
                actor_id=event.actor_id,
                action=event.action,
                reason=event.reason,
                details=event.after or {},
            )
            for event in events
        )
        return sorted(entries, key=lambda item: item.occurred_at, reverse=True)

    def _apply_transition(self, localization: ArticleLocalization, payload) -> None:
        now = utcnow()
        action = payload.action
        if action is ArticleAction.DELETE:
            localization.deleted_at = now
        elif action in {ArticleAction.PUBLISH, ArticleAction.REPUBLISH}:
            self._mark_published(localization, now)
        elif action is ArticleAction.PUBLISH_UPDATE:
            localization.published_revision_id = localization.current_revision_id
            localization.published_at = now
            localization.update_requested_at = None
        elif action is ArticleAction.SCHEDULE:
            localization.status = ArticleStatus.SCHEDULED
            localization.publish_at = payload.publish_at
            localization.unpublish_at = payload.unpublish_at
        elif action is ArticleAction.CANCEL_SCHEDULE:
            localization.status = ArticleStatus.APPROVED
            localization.publish_at = None
            localization.unpublish_at = None
        elif action is ArticleAction.UNPUBLISH:
            localization.status = ArticleStatus.UNPUBLISHED
        else:
            edge = resolve_transition(
                localization.status,
                action,
                reason=getattr(payload, "reason", None) or "scheduler",
                ever_published=localization.first_published_at is not None,
            )
            if edge.target is not None:
                localization.status = edge.target
        localization.lock_version += 1

    def _mark_published(self, localization: ArticleLocalization, now: datetime) -> None:
        localization.status = ArticleStatus.PUBLISHED
        localization.published_revision_id = localization.current_revision_id
        localization.published_at = now
        if localization.first_published_at is None:
            localization.first_published_at = now
        localization.publish_at = None
        localization.update_requested_at = None

    async def _add_localization(self, article, actor, locale, slug, content) -> ArticleLocalization:
        localization = ArticleLocalization(article_id=article.id, locale=locale, slug=slug)
        self.db.add(localization)
        await self.db.flush()
        set_committed_value(localization, "revisions", [])
        set_committed_value(localization, "corrections", [])
        await self._require_media(content.body)
        revision = self._new_revision(
            localization, actor, content, RevisionKind.MANUAL, None, parent_id=None
        )
        await self.db.flush()
        localization.current_revision_id = revision.id
        article.localizations.append(localization)
        return localization

    def _new_revision(self, localization, actor, content, kind, note, parent_id) -> ArticleRevision:
        number = max((item.revision_no for item in localization.revisions), default=0) + 1
        revision = ArticleRevision(
            id=uuid.uuid7(),
            localization_id=localization.id,
            revision_no=number,
            parent_revision_id=parent_id,
            kind=kind,
            title=content.title,
            subtitle=content.subtitle,
            excerpt=content.excerpt,
            body=content.body,
            body_html=render_body(content.body),
            seo_title=content.seo_title,
            seo_description=content.seo_description,
            change_note=note,
            created_by=actor.user.id,
        )
        localization.revisions.append(revision)
        self.db.add(revision)
        return revision

    async def _flush_article(self) -> None:
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            self._reraise_unique(exc)

    async def _commit_article(self) -> None:
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            self._reraise_unique(exc)

    @staticmethod
    def _reraise_unique(exc: IntegrityError) -> None:
        if "unique" not in str(exc.orig).lower() and "duplicate" not in str(exc.orig).lower():
            raise exc
        raise Conflict("Slug or author is already in use") from exc

    async def _article(self, article_id: uuid.UUID) -> Article:
        article = await self.db.scalar(
            select(Article)
            .where(Article.id == article_id)
            .options(
                selectinload(Article.localizations).selectinload(ArticleLocalization.revisions)
            )
        )
        if article is None:
            raise NotFound("Article not found")
        return article

    async def _localization(self, localization_id: uuid.UUID) -> ArticleLocalization:
        localization = await self.db.scalar(
            select(ArticleLocalization)
            .where(ArticleLocalization.id == localization_id)
            .options(
                selectinload(ArticleLocalization.revisions),
                selectinload(ArticleLocalization.article).selectinload(Article.article_authors),
                selectinload(ArticleLocalization.article).selectinload(Article.article_tags),
                selectinload(ArticleLocalization.corrections),
            )
        )
        if localization is None or localization.deleted_at is not None:
            raise NotFound("Article not found")
        return localization

    async def _admin_out(self, article_id: uuid.UUID) -> ArticleAdminOut:
        return self._admin_from(await self._article(article_id))

    def _admin_from(self, article: Article) -> ArticleAdminOut:
        return ArticleAdminOut(
            id=article.id,
            section_id=article.section_id,
            article_type=article.article_type,
            is_breaking=article.is_breaking,
            author_ids=[link.author_id for link in article.article_authors],
            tag_ids=[link.tag_id for link in article.article_tags],
            lead_media_id=article.lead_media_id,
            created_by=article.created_by,
            created_at=article.created_at,
            updated_at=article.updated_at,
            localizations=[
                self._localization_summary(item)
                for item in article.localizations
                if item.deleted_at is None
            ],
        )

    def _localization_summary(self, localization: ArticleLocalization) -> LocalizationSummaryOut:
        current = self._revision(localization, localization.current_revision_id)
        return LocalizationSummaryOut(
            id=localization.id,
            locale=localization.locale,
            slug=localization.slug,
            status=localization.status,
            title=current.title if current else "",
            publish_at=localization.publish_at,
            published_at=localization.published_at,
            has_unpublished_changes=localization.current_revision_id
            != localization.published_revision_id
            and localization.published_revision_id is not None,
            update_requested_at=localization.update_requested_at,
            legal_hold=localization.legal_hold,
            lock_version=localization.lock_version,
        )

    def _localization_out(self, localization: ArticleLocalization) -> LocalizationOut:
        summary = self._localization_summary(localization)
        current = self._revision(localization, localization.current_revision_id)
        if current is None:
            raise NotFound("Revision not found")
        notes = sorted(localization.corrections, key=lambda item: item.created_at)
        return LocalizationOut(
            **summary.model_dump(),
            article_id=localization.article_id,
            current_revision=self._revision_out(current, localization),
            available_actions=available_actions(
                localization.status, ever_published=localization.first_published_at is not None
            ),
            corrections=[CorrectionOut.model_validate(item) for item in notes],
        )

    async def _readable(self, actor: Principal, localization_id: uuid.UUID) -> ArticleLocalization:
        localization = await self._localization(localization_id)
        if not self._can_read(actor, localization.article):
            raise PermissionDenied("You cannot view this article")
        return localization

    def _revision_summary(
        self, revision: ArticleRevision, localization: ArticleLocalization
    ) -> RevisionSummaryOut:
        return RevisionSummaryOut(
            id=revision.id,
            revision_no=revision.revision_no,
            kind=revision.kind,
            title=revision.title,
            change_note=revision.change_note,
            created_by=revision.created_by,
            created_at=revision.created_at,
            is_current=revision.id == localization.current_revision_id,
            is_published=revision.id == localization.published_revision_id,
        )

    def _field_diffs(self, older: ArticleRevision, newer: ArticleRevision) -> list[FieldDiff]:
        fields: list[FieldDiff] = []
        for name in ("title", "subtitle", "excerpt", "seo_title", "seo_description"):
            before = getattr(older, name)
            after = getattr(newer, name)
            if before != after:
                fields.append(FieldDiff(field=name, before=before, after=after))
        old_blocks = older.body.get("content") or []
        new_blocks = newer.body.get("content") or []
        for index in range(max(len(old_blocks), len(new_blocks))):
            before = old_blocks[index] if index < len(old_blocks) else None
            after = new_blocks[index] if index < len(new_blocks) else None
            if before != after:
                fields.append(FieldDiff(field=f"body[{index}]", before=before, after=after))
        return fields

    def _revision_out(
        self, revision: ArticleRevision, localization: ArticleLocalization
    ) -> RevisionOut:
        return RevisionOut(
            id=revision.id,
            revision_no=revision.revision_no,
            kind=revision.kind,
            title=revision.title,
            change_note=revision.change_note,
            created_by=revision.created_by,
            created_at=revision.created_at,
            is_current=revision.id == localization.current_revision_id,
            is_published=revision.id == localization.published_revision_id,
            content=RevisionContent(
                title=revision.title,
                subtitle=revision.subtitle,
                excerpt=revision.excerpt,
                body=revision.body,
                seo_title=revision.seo_title,
                seo_description=revision.seo_description,
            ),
            body_html=revision.body_html,
            parent_revision_id=revision.parent_revision_id,
            restored_from_id=revision.restored_from_id,
        )

    def _summary(self, localization: ArticleLocalization, locale: str) -> ArticleSummaryOut:
        return self._public_out(localization, locale)

    def _public_out(self, localization: ArticleLocalization, locale: str) -> ArticleOut:
        revision = self._revision(
            localization, localization.published_revision_id or localization.current_revision_id
        )
        if (
            revision is None
            or localization.published_at is None
            or localization.first_published_at is None
        ):
            raise NotFound("Article not found")
        article = localization.article
        section_tr = next(
            (item for item in article.section.translations if item.locale == locale),
            None,
        )
        bylines = []
        for link in sorted(article.article_authors, key=lambda item: item.position):
            translation = next(
                (item for item in link.author.translations if item.locale == locale), None
            )
            if translation is None and link.author.translations:
                translation = link.author.translations[0]
            if translation is not None:
                bylines.append(
                    BylineOut(
                        author_id=link.author_id,
                        display_name=translation.display_name,
                        slug=translation.slug,
                    )
                )
        tags = [
            public
            for link in article.article_tags
            if (public := tag_public(link.tag, locale)) is not None
        ]
        alternates = [
            AlternateOut(locale=item.locale, slug=item.slug)
            for item in article.localizations
            if item.status is ArticleStatus.PUBLISHED and item.id != localization.id
        ]
        return ArticleOut(
            id=article.id,
            locale=localization.locale,
            slug=localization.slug,
            title=revision.title,
            excerpt=revision.excerpt,
            article_type=article.article_type,
            is_breaking=article.is_breaking,
            section=SectionRefOut(
                id=article.section_id,
                name=section_tr.name if section_tr else article.section.key,
                slug=section_tr.slug if section_tr else article.section.key,
            ),
            bylines=bylines,
            lead_image_url=(
                f"/media/{article.lead_media_id}" if article.lead_media_id is not None else None
            ),
            published_at=localization.published_at,
            first_published_at=localization.first_published_at,
            subtitle=revision.subtitle,
            body_html=revision.body_html,
            tags=tags,
            corrections=[CorrectionOut.model_validate(item) for item in localization.corrections],
            alternates=alternates,
            seo_title=revision.seo_title,
            seo_description=revision.seo_description,
        )

    def _revision(
        self, localization: ArticleLocalization, revision_id: uuid.UUID | None
    ) -> ArticleRevision | None:
        return next((item for item in localization.revisions if item.id == revision_id), None)

    def _lock(self, article: Article) -> int:
        return max((item.lock_version for item in article.localizations), default=1)

    def _require(self, actor: Principal, perm: Perm, section_id: uuid.UUID) -> None:
        if not actor.grants.has(perm, section_id=section_id):
            raise PermissionDenied(f"Missing permission: {perm.value}")

    def _require_edit(
        self, actor: Principal, article: Article, localization: ArticleLocalization | None
    ) -> None:
        if actor.grants.has(Perm.ARTICLE_EDIT, section_id=article.section_id):
            if localization is not None and localization.status is ArticleStatus.ARCHIVED:
                raise PermissionDenied("Archived stories cannot be edited")
            return
        if (
            article.created_by == actor.user.id
            and actor.grants.has_anywhere(Perm.ARTICLE_EDIT_OWN)
            and localization is not None
            and localization.status in EDITABLE_BY_OWNER
        ):
            return
        raise PermissionDenied("You cannot edit this article")

    def _coalesce_autosave(
        self, localization: ArticleLocalization, actor: Principal, payload: RevisionCreate
    ) -> ArticleRevision | None:
        """Replace the open autosave. Five quiet minutes, or a manual save, starts a new row."""
        current = self._revision(localization, localization.current_revision_id)
        if current is None or not self._autosave_open(current, actor, localization):
            return None
        allowed = {current.id}
        if current.parent_revision_id is not None:
            allowed.add(current.parent_revision_id)
        if payload.base_revision_id not in allowed:
            raise RevisionConflict("Revision is stale")
        content = payload.content
        current.title = content.title
        current.subtitle = content.subtitle
        current.excerpt = content.excerpt
        current.body = content.body
        current.body_html = render_body(content.body)
        current.seo_title = content.seo_title
        current.seo_description = content.seo_description
        current.change_note = payload.change_note
        return current

    def _autosave_open(
        self,
        current: ArticleRevision | None,
        actor: Principal,
        localization: ArticleLocalization,
    ) -> bool:
        if current is None or current.kind is not RevisionKind.AUTOSAVE:
            return False
        if current.created_by != actor.user.id:
            return False
        if current.id == localization.published_revision_id:
            return False
        created = current.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if utcnow() - created > AUTOSAVE_WINDOW:
            return False
        return not any(
            item.id != current.id
            and (item.parent_revision_id == current.id or item.restored_from_id == current.id)
            for item in localization.revisions
        )

    def _writer_proposal(self, actor: Principal, localization: ArticleLocalization) -> bool:
        return (
            localization.status is ArticleStatus.PUBLISHED
            and localization.article.created_by == actor.user.id
            and not actor.grants.has(
                Perm.ARTICLE_PUBLISH, section_id=localization.article.section_id
            )
        )

    @staticmethod
    def _require_reason(reason: str, action: str) -> None:
        if not reason or not reason.strip():
            raise ReasonRequired(f"A reason is required to {action}")

    def _require_transition(self, actor: Principal, article: Article, edge) -> None:
        """Submit and delete-draft are the writer's own story, unless they can edit the desk."""
        owns = article.created_by == actor.user.id
        can_edit = actor.grants.has(Perm.ARTICLE_EDIT, section_id=article.section_id)
        if edge.owner_may_act and not can_edit:
            if not owns or not actor.grants.has_anywhere(edge.permission):
                raise PermissionDenied("You can only submit or delete your own draft")
            return
        self._require(actor, edge.permission, article.section_id)

    def _can_read(self, actor: Principal, article: Article) -> bool:
        if actor.user.kind is not UserKind.STAFF:
            return False
        if article.created_by == actor.user.id:
            return True
        return actor.grants.has(
            Perm.ARTICLE_READ, section_id=article.section_id
        ) or actor.grants.has_anywhere(Perm.ARTICLE_READ)


class _Due:
    def __init__(self, action: ArticleAction) -> None:
        self.action = action
        self.publish_at = None
        self.unpublish_at = None
        self.reason = "scheduler"
        self.takedown_reason = None


async def author_for_user(db: AsyncSession, user_id: uuid.UUID) -> Author | None:
    return await db.scalar(
        select(Author).where(Author.user_id == user_id).options(selectinload(Author.translations))
    )


async def translation_name(author: Author, locale: str) -> str:
    row = next((item for item in author.translations if item.locale == locale), None)
    if row is None and author.translations:
        row = author.translations[0]
    return row.display_name if row else author.key
