import uuid

from newsroom.core.schemas import Schema, UtcDatetime


class MediaTranslationIn(Schema):
    locale: str
    caption: str | None = None
    alt_text: str | None = None


class MediaTranslationOut(Schema):
    locale: str
    caption: str | None
    alt_text: str | None


class MediaOut(Schema):
    id: uuid.UUID
    mime_type: str
    width: int | None
    height: int | None
    byte_size: int
    credit: str | None
    created_at: UtcDatetime
    translations: list[MediaTranslationOut]
