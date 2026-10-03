import uuid
from enum import StrEnum
from typing import Any

from pydantic import Field

from newsroom.articles.workflow import ArticleAction, ArticleStatus, CorrectionKind, TakedownReason
from newsroom.core.schemas import Schema, Slug, UtcDatetime
from newsroom.taxonomy.schemas import TagOut


class ArticleType(StrEnum):
    NEWS = "news"
    OPINION = "opinion"
    ANALYSIS = "analysis"
    FEATURE = "feature"
    INTERVIEW = "interview"


class RevisionKind(StrEnum):
    MANUAL = "manual"
    AUTOSAVE = "autosave"
    RESTORE = "restore"
    SYSTEM = "system"


# ---- Public ---------------------------------------------------------------------------------


class BylineOut(Schema):
    author_id: uuid.UUID
    display_name: str
    slug: str


class SectionRefOut(Schema):
    id: uuid.UUID
    name: str
    slug: str


class ArticleSummaryOut(Schema):
    id: uuid.UUID
    locale: str
    slug: str
    title: str
    excerpt: str | None
    article_type: ArticleType
    is_breaking: bool
    section: SectionRefOut
    bylines: list[BylineOut]
    lead_image_url: str | None = None
    published_at: UtcDatetime
    first_published_at: UtcDatetime


class CorrectionOut(Schema):
    id: uuid.UUID
    kind: CorrectionKind
    text: str
    created_at: UtcDatetime


class AlternateOut(Schema):
    locale: str
    slug: str


class ArticleOut(ArticleSummaryOut):
    subtitle: str | None
    body_html: str
    tags: list[TagOut]
    corrections: list[CorrectionOut]
    alternates: list[AlternateOut] = Field(
        default=[], description="Published translations of the same article"
    )
    seo_title: str | None = None
    seo_description: str | None = None


# ---- Admin ----------------------------------------------------------------------------------


class RevisionContent(Schema):
    title: str = Field(min_length=1, max_length=300)
    subtitle: str | None = Field(default=None, max_length=500)
    excerpt: str | None = Field(default=None, max_length=1000)
    body: dict[str, Any] = Field(description="Editor document (source of truth)")
    seo_title: str | None = Field(default=None, max_length=300)
    seo_description: str | None = Field(default=None, max_length=500)


class ArticleCreate(Schema):
    section_id: uuid.UUID
    article_type: ArticleType = ArticleType.NEWS
    author_ids: list[uuid.UUID] = Field(min_length=1)
    tag_ids: list[uuid.UUID] = []
    lead_media_id: uuid.UUID | None = None
    is_breaking: bool = False
    locale: str = Field(max_length=10)
    slug: Slug
    content: RevisionContent


class LeadImageUpdate(Schema):
    media_id: uuid.UUID | None = None


class ArticleUpdate(Schema):
    lock_version: int
    section_id: uuid.UUID | None = None
    article_type: ArticleType | None = None
    author_ids: list[uuid.UUID] | None = None
    tag_ids: list[uuid.UUID] | None = None
    lead_media_id: uuid.UUID | None = None
    is_breaking: bool | None = None


class LocalizationCreate(Schema):
    locale: str = Field(max_length=10)
    slug: Slug
    content: RevisionContent
    translated_from_revision_id: uuid.UUID | None = None


class LocalizationSummaryOut(Schema):
    id: uuid.UUID
    locale: str
    slug: str
    status: ArticleStatus
    title: str
    publish_at: UtcDatetime | None
    published_at: UtcDatetime | None
    has_unpublished_changes: bool
    update_requested_at: UtcDatetime | None
    legal_hold: bool = False
    reviewed_by: uuid.UUID | None = None
    updated_at: UtcDatetime
    lock_version: int


class ArticleAdminOut(Schema):
    id: uuid.UUID
    section_id: uuid.UUID
    article_type: ArticleType
    is_breaking: bool
    author_ids: list[uuid.UUID]
    tag_ids: list[uuid.UUID]
    lead_media_id: uuid.UUID | None
    created_by: uuid.UUID
    created_at: UtcDatetime
    updated_at: UtcDatetime
    localizations: list[LocalizationSummaryOut]


class RevisionSummaryOut(Schema):
    id: uuid.UUID
    revision_no: int
    kind: RevisionKind
    title: str
    change_note: str | None
    created_by: uuid.UUID
    created_at: UtcDatetime
    is_current: bool
    is_published: bool


class RevisionOut(RevisionSummaryOut):
    content: RevisionContent
    body_html: str
    parent_revision_id: uuid.UUID | None
    restored_from_id: uuid.UUID | None


class LocalizationOut(LocalizationSummaryOut):
    article_id: uuid.UUID
    current_revision: RevisionOut
    available_actions: list[ArticleAction]
    corrections: list[CorrectionOut] = []


class SlugChange(Schema):
    slug: Slug


class RevisionCreate(Schema):
    base_revision_id: uuid.UUID = Field(description="Revision the editor started from")
    content: RevisionContent
    kind: RevisionKind = RevisionKind.MANUAL
    change_note: str | None = Field(default=None, max_length=500)


class RestoreRequest(Schema):
    base_revision_id: uuid.UUID
    change_note: str | None = Field(default=None, max_length=500)


class FieldDiff(Schema):
    field: str
    before: Any
    after: Any


class RevisionDiffOut(Schema):
    from_revision_id: uuid.UUID
    to_revision_id: uuid.UUID
    fields: list[FieldDiff]


class ReasonRequest(Schema):
    reason: str = Field(min_length=1, max_length=2000)


class TransitionRequest(Schema):
    action: ArticleAction
    lock_version: int
    reason: str | None = Field(default=None, max_length=2000)
    takedown_reason: TakedownReason | None = Field(
        default=None, description="Required when action is `unpublish`"
    )
    publish_at: UtcDatetime | None = Field(default=None, description="Required for `schedule`")
    unpublish_at: UtcDatetime | None = None


class HistoryEntryKind(StrEnum):
    REVISION = "revision"
    EVENT = "event"


class HistoryEntryOut(Schema):
    kind: HistoryEntryKind
    occurred_at: UtcDatetime
    actor_id: uuid.UUID | None
    action: str
    revision_id: uuid.UUID | None = None
    reason: str | None = None
    details: dict[str, Any] = {}


class CorrectionCreate(Schema):
    kind: CorrectionKind = CorrectionKind.CORRECTION
    text: str = Field(min_length=1, max_length=2000)
