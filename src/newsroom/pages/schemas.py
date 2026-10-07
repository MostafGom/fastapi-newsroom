import uuid
from typing import Any

from pydantic import Field

from newsroom.core.schemas import Schema, Slug
from newsroom.pages.models import PageStatus


class PageCreate(Schema):
    key: str = Field(pattern=r"^[a-z0-9_-]+$", max_length=64)
    sort_order: int = 0


class PageTranslationIn(Schema):
    locale: str = Field(max_length=10)
    title: str = Field(min_length=1, max_length=300)
    slug: Slug
    body: dict[str, Any]
    status: PageStatus = PageStatus.DRAFT


class PageTranslationOut(Schema):
    locale: str
    title: str
    slug: str
    body: dict[str, Any]
    body_html: str
    status: PageStatus


class PageAdminOut(Schema):
    id: uuid.UUID
    key: str
    sort_order: int
    translations: list[PageTranslationOut]


class PagePublicOut(Schema):
    id: uuid.UUID
    key: str
    title: str
    slug: str
    body_html: str


class PageLink(Schema):
    title: str
    slug: str
