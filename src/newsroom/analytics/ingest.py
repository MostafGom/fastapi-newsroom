"""Batch inserts into the analytics database.

A crashed batch is a loss, not an editorial failure.
"""

import time
import uuid
from typing import Any

import structlog
from sqlalchemy import insert
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from newsroom.analytics.models import AnalyticsEvent
from newsroom.analytics.partitions import ensure_partitions

log = structlog.get_logger("newsroom.analytics")


class RateGate:
    """Sliding window of accepted events. Keys are visitor ids and client addresses."""

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str, *, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else now
        recent = [hit for hit in self._hits.get(key, []) if moment - hit < self.window_seconds]
        if len(recent) >= self.limit:
            self._hits[key] = recent
            return False
        recent.append(moment)
        self._hits[key] = recent
        if len(self._hits) > 10_000:
            cutoff = moment - self.window_seconds
            self._hits = {
                name: hits for name, hits in self._hits.items() if hits and hits[-1] >= cutoff
            }
        return True


class EventBuffer:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        flush_seconds: float,
        flush_size: int,
        rate_limit: int,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.flush_seconds = flush_seconds
        self.flush_size = flush_size
        self.gate = RateGate(rate_limit)
        self._pending: list[dict[str, Any]] = []

    def allow(self, visitor_id: str, ip: str | None) -> bool:
        if not self.gate.allow(visitor_id):
            return False
        return ip is None or self.gate.allow(f"ip:{ip}")

    async def add(self, row: dict[str, Any]) -> None:
        if self.flush_seconds <= 0:
            await self._write([row])
            return
        self._pending.append(row)
        if len(self._pending) < self.flush_size:
            return
        batch = self._pending
        self._pending = []
        await self._write(batch)

    async def flush(self) -> None:
        if not self._pending:
            return
        batch = self._pending
        self._pending = []
        await self._write(batch)

    async def _write(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        async with self.sessionmaker() as db:
            try:
                await self._insert(db, rows)
            except ProgrammingError as exc:
                await db.rollback()
                if "no partition" not in str(exc).lower():
                    raise
                await ensure_partitions(db)
                await self._insert(db, rows)
            await db.commit()

    async def _insert(self, db: AsyncSession, rows: list[dict[str, Any]]) -> None:
        prepared = [{**row, "id": row.get("id") or uuid.uuid7()} for row in rows]
        await db.execute(insert(AnalyticsEvent).values(prepared))
