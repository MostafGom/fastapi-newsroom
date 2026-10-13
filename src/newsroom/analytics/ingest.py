"""Batch inserts into the analytics database.

A crashed batch is a loss, not an editorial failure.
"""

import time
import uuid
from collections import deque
from typing import Any

import structlog
from sqlalchemy import insert
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from newsroom.analytics.models import AnalyticsEvent
from newsroom.analytics.partitions import ensure_partitions

log = structlog.get_logger("newsroom.analytics")


class RateGate:
    """Sliding window of accepted events. Keys are visitor ids and client addresses.

    Memory and time stay bounded when a client invents a new visitor id per request: a
    refused event records nothing, expired keys are swept at most once per window, and a
    new key is refused once ``max_keys`` keys are live.
    """

    def __init__(self, limit: int, window_seconds: float = 60.0, max_keys: int = 100_000) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._next_sweep = 0.0

    def allow(self, *keys: str, now: float | None = None) -> bool:
        """Count one event against every key, or against none if any key is full."""
        moment = time.monotonic() if now is None else now
        cutoff = moment - self.window_seconds
        if moment >= self._next_sweep:
            self._sweep(cutoff)
            self._next_sweep = moment + self.window_seconds
        windows: list[deque[float] | None] = []
        for key in keys:
            hits = self._hits.get(key)
            if hits is not None:
                while hits and hits[0] <= cutoff:
                    hits.popleft()
                if len(hits) >= self.limit:
                    return False
            windows.append(hits)
        new_keys = sum(1 for hits in windows if hits is None)
        if new_keys and len(self._hits) + new_keys > self.max_keys:
            return False
        for key, hits in zip(keys, windows, strict=True):
            if hits is None:
                hits = self._hits[key] = deque()
            hits.append(moment)
        return True

    def _sweep(self, cutoff: float) -> None:
        self._hits = {key: hits for key, hits in self._hits.items() if hits and hits[-1] > cutoff}

    def __len__(self) -> int:
        return len(self._hits)


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
        if ip is None:
            return self.gate.allow(visitor_id)
        return self.gate.allow(f"ip:{ip}", visitor_id)

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
