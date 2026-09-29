import uuid

from pydantic import Field

from newsroom.core.schemas import Schema, UtcDatetime


class CommentCreate(Schema):
    body: str = Field(min_length=1, max_length=2000)


class CommentOut(Schema):
    id: uuid.UUID
    localization_id: uuid.UUID
    author_name: str
    body: str
    created_at: UtcDatetime
    mine: bool = False
