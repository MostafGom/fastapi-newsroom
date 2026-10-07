"""Daily partitions for raw events. Retention is a drop of an old partition, not a row delete."""

import re
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_NAME = re.compile(r"^events_y(\d{4})m(\d{2})d(\d{2})$")


def partition_name(day: date) -> str:
    name = f"events_y{day.year:04d}m{day.month:02d}d{day.day:02d}"
    if _NAME.fullmatch(name) is None:
        raise RuntimeError("partition name is not a calendar day")
    return name


def _bounds(day: date) -> tuple[str, str]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


async def ensure_partitions(
    db: AsyncSession, *, today: date | None = None, behind: int = 1, ahead: int = 2
) -> None:
    """Create the partitions a live insert or the open hour can land in."""
    anchor = today or datetime.now(UTC).date()
    for offset in range(-behind, ahead + 1):
        day = anchor + timedelta(days=offset)
        name = partition_name(day)
        start, end = _bounds(day)
        await db.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF events "
                f"FOR VALUES FROM ('{start}') TO ('{end}')"
            )
        )


async def drop_expired_partitions(db: AsyncSession, retention_days: int) -> int:
    """Drop day partitions older than the retention window. Rollups are left in place."""
    cutoff = datetime.now(UTC).date() - timedelta(days=retention_days)
    names = (
        await db.scalars(
            text(
                "SELECT child.relname FROM pg_inherits "
                "JOIN pg_class child ON child.oid = pg_inherits.inhrelid "
                "JOIN pg_class parent ON parent.oid = pg_inherits.inhparent "
                "WHERE parent.relname = 'events'"
            )
        )
    ).all()
    dropped = 0
    for name in names:
        match = _NAME.fullmatch(name)
        if match is None:
            continue
        year, month, day = (int(part) for part in match.groups())
        if date(year, month, day) >= cutoff:
            continue
        await db.execute(text(f"DROP TABLE IF EXISTS {name}"))
        dropped += 1
    return dropped
