import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.audit.models import AuditEvent
from newsroom.audit.schemas import AuditEventOut
from newsroom.core.context import client_ip_var, request_id_var
from newsroom.core.schemas import Page, PageParams, decode_cursor, encode_cursor


def record_event(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> AuditEvent:
    """Stage an audit event in the caller's transaction; it commits (or rolls back) with it."""
    event = AuditEvent(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        before=before,
        after=after,
        reason=reason,
        ip=client_ip_var.get(),
        request_id=request_id_var.get(),
    )
    db.add(event)
    return event


class AuditService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_events(
        self,
        paging: PageParams,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        actor_id: uuid.UUID | None = None,
        action: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> Page[AuditEventOut]:
        stmt = select(AuditEvent).order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        if entity_type:
            stmt = stmt.where(AuditEvent.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(AuditEvent.entity_id == entity_id)
        if actor_id is not None:
            stmt = stmt.where(AuditEvent.actor_id == actor_id)
        if action:
            stmt = stmt.where(AuditEvent.action == action)
        if since is not None:
            stmt = stmt.where(AuditEvent.occurred_at >= since)
        if until is not None:
            stmt = stmt.where(AuditEvent.occurred_at <= until)
        if paging.cursor:
            raw = decode_cursor(paging.cursor)
            stmt = stmt.where(
                tuple_(AuditEvent.occurred_at, AuditEvent.id)
                < tuple_(datetime.fromisoformat(raw["occurred_at"]), uuid.UUID(raw["id"]))
            )
        rows = list((await self.db.scalars(stmt.limit(paging.limit + 1))).all())
        next_cursor = None
        if len(rows) > paging.limit:
            rows = rows[: paging.limit]
            last = rows[-1]
            next_cursor = encode_cursor(
                {"occurred_at": last.occurred_at.isoformat(), "id": str(last.id)}
            )
        return Page(
            items=[AuditEventOut.model_validate(row) for row in rows], next_cursor=next_cursor
        )
