"""Tables for the analytics database. This metadata is not registered on the editorial Base."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from newsroom.core.models import NAMING_CONVENTION

SURFACES = ("article", "page", "home", "section", "tag", "search")
OTHER_SURFACES = ("home", "section", "tag", "page", "search")
EVENT_TYPES = ("page_view", "engagement", "click")
REFERRER_CLASSES = ("direct", "search", "social", "internal", "other")
DEVICE_CLASSES = ("desktop", "mobile", "tablet", "other")


class AnalyticsBase(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime: DateTime(timezone=True)}


class AnalyticsEvent(AnalyticsBase):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("type IN ('page_view', 'engagement', 'click')", name="type"),
        CheckConstraint(
            "surface IN ('article', 'page', 'home', 'section', 'tag', 'search')", name="surface"
        ),
        CheckConstraint(
            "referrer_class IN ('direct', 'search', 'social', 'internal', 'other')",
            name="referrer_class",
        ),
        CheckConstraint(
            "device_class IN ('desktop', 'mobile', 'tablet', 'other')", name="device_class"
        ),
        CheckConstraint("engaged_ms >= 0 AND engaged_ms <= 1800000", name="engaged_ms"),
        CheckConstraint("scroll_pct >= 0 AND scroll_pct <= 100", name="scroll_pct"),
        Index("ix_events_occurred_at", "occurred_at", postgresql_using="brin"),
        {"postgresql_partition_by": "RANGE (occurred_at)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    occurred_at: Mapped[datetime] = mapped_column(primary_key=True, server_default=func.now())
    type: Mapped[str] = mapped_column(String(16))
    view_id: Mapped[uuid.UUID]
    localization_id: Mapped[uuid.UUID | None]
    article_id: Mapped[uuid.UUID | None]
    section_id: Mapped[uuid.UUID | None]
    page_id: Mapped[uuid.UUID | None]
    tag_id: Mapped[uuid.UUID | None]
    locale: Mapped[str] = mapped_column(String(10))
    surface: Mapped[str] = mapped_column(String(16))
    visitor_id: Mapped[uuid.UUID]
    referrer_class: Mapped[str] = mapped_column(String(16))
    device_class: Mapped[str] = mapped_column(String(16))
    engaged_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    scroll_pct: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    click_target: Mapped[str | None] = mapped_column(String(200))


class _Measure:
    views: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    unique_visitors: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    engaged_ms_sum: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    engaged_views: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    scroll_75: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    clicks: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class ArticleStatsHourly(_Measure, AnalyticsBase):
    __tablename__ = "stats_article_hourly"
    __table_args__ = (Index("ix_stats_article_hourly_section_bucket", "section_id", "bucket"),)

    localization_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    bucket: Mapped[datetime] = mapped_column(primary_key=True)
    article_id: Mapped[uuid.UUID]
    section_id: Mapped[uuid.UUID]
    locale: Mapped[str] = mapped_column(String(10))


class ArticleStatsDaily(_Measure, AnalyticsBase):
    __tablename__ = "stats_article_daily"
    __table_args__ = (Index("ix_stats_article_daily_section_bucket", "section_id", "bucket"),)

    localization_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    bucket: Mapped[datetime] = mapped_column(primary_key=True)
    article_id: Mapped[uuid.UUID]
    section_id: Mapped[uuid.UUID]
    locale: Mapped[str] = mapped_column(String(10))


class ArticleStatsWindow(_Measure, AnalyticsBase):
    __tablename__ = "stats_article_window"
    __table_args__ = (Index("ix_stats_article_window_section", "window_days", "section_id"),)

    localization_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    window_days: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    article_id: Mapped[uuid.UUID]
    section_id: Mapped[uuid.UUID]
    locale: Mapped[str] = mapped_column(String(10))


class ArticleReferrerDaily(AnalyticsBase):
    __tablename__ = "stats_article_referrer_daily"

    localization_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    bucket: Mapped[datetime] = mapped_column(primary_key=True)
    referrer_class: Mapped[str] = mapped_column(String(16), primary_key=True)
    views: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class SiteStatsHourly(_Measure, AnalyticsBase):
    __tablename__ = "stats_site_hourly"

    bucket: Mapped[datetime] = mapped_column(primary_key=True)
    surface: Mapped[str] = mapped_column(String(16), primary_key=True)


class SiteStatsDaily(_Measure, AnalyticsBase):
    __tablename__ = "stats_site_daily"

    bucket: Mapped[datetime] = mapped_column(primary_key=True)
    surface: Mapped[str] = mapped_column(String(16), primary_key=True)


class ArticleDeviceDaily(AnalyticsBase):
    __tablename__ = "stats_article_device_daily"
    __table_args__ = (
        CheckConstraint(
            "device_class IN ('desktop', 'mobile', 'tablet', 'other')", name="device_class"
        ),
    )

    localization_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    bucket: Mapped[datetime] = mapped_column(primary_key=True)
    device_class: Mapped[str] = mapped_column(String(16), primary_key=True)
    views: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class ArticleClickDaily(AnalyticsBase):
    __tablename__ = "stats_article_click_daily"

    localization_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    bucket: Mapped[datetime] = mapped_column(primary_key=True)
    click_target: Mapped[str] = mapped_column(String(200), primary_key=True)
    clicks: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class SiteStatsWindow(_Measure, AnalyticsBase):
    __tablename__ = "stats_site_window"

    window_days: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    surface: Mapped[str] = mapped_column(String(16), primary_key=True)


class SectionStatsHourly(_Measure, AnalyticsBase):
    __tablename__ = "stats_section_hourly"

    section_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    bucket: Mapped[datetime] = mapped_column(primary_key=True)


class SectionStatsDaily(_Measure, AnalyticsBase):
    __tablename__ = "stats_section_daily"

    section_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    bucket: Mapped[datetime] = mapped_column(primary_key=True)


class SectionStatsWindow(_Measure, AnalyticsBase):
    __tablename__ = "stats_section_window"

    section_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    window_days: Mapped[int] = mapped_column(SmallInteger, primary_key=True)


class SectionListingWindow(_Measure, AnalyticsBase):
    """Visits to a section's public list. Article reads stay on the article rollups."""

    __tablename__ = "stats_section_listing_window"

    section_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    window_days: Mapped[int] = mapped_column(SmallInteger, primary_key=True)


class PageStatsWindow(_Measure, AnalyticsBase):
    __tablename__ = "stats_page_window"

    page_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    window_days: Mapped[int] = mapped_column(SmallInteger, primary_key=True)


class TagStatsWindow(_Measure, AnalyticsBase):
    __tablename__ = "stats_tag_window"

    tag_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    window_days: Mapped[int] = mapped_column(SmallInteger, primary_key=True)


def truncate_statement() -> str:
    names = ", ".join(table.name for table in AnalyticsBase.metadata.sorted_tables)
    return f"TRUNCATE {names}"
