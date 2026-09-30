import uuid

from pydantic import Field

from newsroom.core.schemas import Schema, UtcDatetime


class MediaTranslationIn(Schema):
    locale: str
    caption: str | None = None
    alt_text: str | None = None


class MediaTranslationOut(Schema):
    locale: str
    caption: str | None
    alt_text: str | None


class MediaNameIn(Schema):
    filename: str = Field(min_length=1, max_length=200)


class MediaOut(Schema):
    id: uuid.UUID
    filename: str | None
    mime_type: str
    width: int | None
    height: int | None
    byte_size: int
    credit: str | None
    created_at: UtcDatetime
    translations: list[MediaTranslationOut]
