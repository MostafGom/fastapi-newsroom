"""Worker rollups. The desk reads the tables this module fills; it does not scan events."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.analytics.partitions import drop_expired_partitions, ensure_partitions
from newsroom.analytics.repository import AnalyticsRepository

WINDOWS = (1, 7, 28)


def hour_bucket(moment: datetime) -> datetime:
    current = moment.astimezone(UTC)
    return current.replace(minute=0, second=0, microsecond=0)


def day_bucket(moment: datetime) -> datetime:
    current = moment.astimezone(UTC)
    return current.replace(hour=0, minute=0, second=0, microsecond=0)


def window_start(days: int, moment: datetime) -> datetime:
    return day_bucket(moment) - timedelta(days=days - 1)


async def run_refresh(db: AsyncSession) -> int:
    from newsroom.core.config import get_settings

    return await refresh_analytics(db, retention_days=get_settings().analytics_raw_retention_days)


ANALYTICS_JOBS = {"refresh_analytics": run_refresh}


async def refresh_analytics(
    db: AsyncSession, *, retention_days: int, now: datetime | None = None
) -> int:
    """Rebuild the open hours, today, and the desk windows. Returns dropped partitions."""
    moment = now or datetime.now(UTC)
    await ensure_partitions(db, today=moment.date())
    dropped = await drop_expired_partitions(db, retention_days)
    repo = AnalyticsRepository(db)
    hour = hour_bucket(moment)
    previous = hour - timedelta(hours=1)
    today = day_bucket(moment)
    yesterday = today - timedelta(days=1)
    for bucket in (previous, hour):
        end = bucket + timedelta(hours=1)
        await repo.replace_article_bucket("stats_article_hourly", bucket, end, bucket)
        await repo.replace_site_bucket("stats_site_hourly", bucket, end, bucket)
        await repo.replace_section_bucket("stats_section_hourly", bucket, end, bucket)
    for bucket in (yesterday, today):
        end = bucket + timedelta(days=1)
        await repo.replace_article_bucket("stats_article_daily", bucket, end, bucket)
        await repo.replace_site_bucket("stats_site_daily", bucket, end, bucket)
        await repo.replace_section_bucket("stats_section_daily", bucket, end, bucket)
        await repo.replace_referrers(bucket, end, bucket)
        await repo.replace_devices(bucket, end, bucket)
        await repo.replace_clicks(bucket, end, bucket)
    for days in WINDOWS:
        await repo.replace_windows(days, window_start(days, moment))
    await db.commit()
    return dropped
