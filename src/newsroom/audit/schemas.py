import uuid
from typing import Any

from newsroom.core.schemas import Schema, UtcDatetime


class AuditEventOut(Schema):
    id: uuid.UUID
    occurred_at: UtcDatetime
    actor_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None
    request_id: str | None
