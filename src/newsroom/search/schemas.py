import uuid
from dataclasses import dataclass
from datetime import datetime

from newsroom.core.schemas import Schema, UtcDatetime


class SearchHit(Schema):
    localization_id: uuid.UUID
    locale: str
    slug: str
    title: str
    section_name: str
    section_slug: str
    published_at: UtcDatetime
    snippet: str
    rank: float | None = None


@dataclass(frozen=True, slots=True)
class IndexedStory:
    localization_id: uuid.UUID
    locale: str
    slug: str
    title: str
    excerpt: str | None
    body_text: str
    section_id: uuid.UUID
    section_slug: str
    section_name: str
    tag_slugs: list[str]
    extra_text: str
    published_at: datetime


@dataclass(frozen=True, slots=True)
class SearchFilters:
    locale: str
    text: str
    section_slug: str | None = None
    tag_slug: str | None = None
    since: datetime | None = None
    until: datetime | None = None
