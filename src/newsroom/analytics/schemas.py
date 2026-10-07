import uuid
from typing import Literal

from pydantic import Field

from newsroom.core.schemas import Schema

EventType = Literal["page_view", "engagement", "click"]


class CollectIn(Schema):
    token: str = Field(min_length=1, max_length=4000)
    type: EventType
    view_id: uuid.UUID
    engaged_ms: int = Field(default=0, ge=0, le=30 * 60 * 1000)
    scroll_pct: int = Field(default=0, ge=0, le=100)
    click_target: str | None = Field(default=None, max_length=200)
