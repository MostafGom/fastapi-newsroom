import uuid

from pydantic import Field

from newsroom.core.schemas import Schema, Slug


class SectionTranslationIn(Schema):
    locale: str = Field(max_length=10)
    name: str = Field(min_length=1, max_length=120)
    slug: Slug
    description: str | None = None


class SectionCreate(Schema):
    key: str = Field(pattern=r"^[a-z0-9_-]+$", max_length=64)
    parent_id: uuid.UUID | None = None
    sort_order: int = 0
    translations: list[SectionTranslationIn] = Field(min_length=1)


class SectionUpdate(Schema):
    parent_id: uuid.UUID | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    translations: list[SectionTranslationIn] | None = None


class SectionOut(Schema):
    """A section rendered in one locale (public API)."""

    id: uuid.UUID
    key: str
    parent_id: uuid.UUID | None
    name: str
    slug: str
    description: str | None = None
    children: list[SectionOut] = []


class SectionAdminOut(Schema):
    id: uuid.UUID
    key: str
    parent_id: uuid.UUID | None
    sort_order: int
    is_active: bool
    translations: list[SectionTranslationIn]


class TagTranslationIn(Schema):
    locale: str = Field(max_length=10)
    name: str = Field(min_length=1, max_length=120)
    slug: Slug


class TagCreate(Schema):
    key: str = Field(pattern=r"^[a-z0-9_-]+$", max_length=64)
    translations: list[TagTranslationIn] = Field(min_length=1)


class TagOut(Schema):
    id: uuid.UUID
    key: str
    name: str
    slug: str


class TagAdminOut(Schema):
    id: uuid.UUID
    key: str
    translations: list[TagTranslationIn]
