import uuid

from pydantic import Field

from newsroom.core.schemas import Schema


class HomepageUpdate(Schema):
    locale: str = Field(max_length=10)
    localization_ids: list[uuid.UUID] = Field(max_length=12)
    labels: list[str | None] = Field(default_factory=list, max_length=12)
