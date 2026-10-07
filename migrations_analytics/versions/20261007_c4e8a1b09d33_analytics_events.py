"""analytics events and rollups

Revision ID: c4e8a1b09d33
Revises:
Create Date: 2026-10-07 08:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a1b09d33"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("view_id", sa.Uuid(), nullable=False),
        sa.Column("localization_id", sa.Uuid(), nullable=True),
        sa.Column("article_id", sa.Uuid(), nullable=True),
        sa.Column("section_id", sa.Uuid(), nullable=True),
        sa.Column("page_id", sa.Uuid(), nullable=True),
        sa.Column("locale", sa.String(length=10), nullable=False),
        sa.Column("surface", sa.String(length=16), nullable=False),
        sa.Column("visitor_id", sa.Uuid(), nullable=False),
        sa.Column("referrer_class", sa.String(length=16), nullable=False),
        sa.Column("device_class", sa.String(length=16), nullable=False),
        sa.Column("engaged_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("scroll_pct", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("click_target", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("id", "occurred_at", name="pk_events"),
        sa.CheckConstraint("type IN ('page_view', 'engagement', 'click')", name="ck_events_type"),
        sa.CheckConstraint(
            "surface IN ('article', 'page', 'home', 'section', 'tag')", name="ck_events_surface"
        ),
        sa.CheckConstraint(
            "referrer_class IN ('direct', 'search', 'social', 'internal', 'other')",
            name="ck_events_referrer_class",
        ),
        sa.CheckConstraint(
            "device_class IN ('desktop', 'mobile', 'tablet', 'other')",
            name="ck_events_device_class",
        ),
        sa.CheckConstraint(
            "engaged_ms >= 0 AND engaged_ms <= 1800000", name="ck_events_engaged_ms"
        ),
        sa.CheckConstraint("scroll_pct >= 0 AND scroll_pct <= 100", name="ck_events_scroll_pct"),
        postgresql_partition_by="RANGE (occurred_at)",
    )
    op.create_index(
        "ix_events_occurred_at", "events", ["occurred_at"], unique=False, postgresql_using="brin"
    )
    _measure_table(
        "stats_article_hourly",
        [
            sa.Column("localization_id", sa.Uuid(), nullable=False),
            sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
            sa.Column("article_id", sa.Uuid(), nullable=False),
            sa.Column("section_id", sa.Uuid(), nullable=False),
            sa.Column("locale", sa.String(length=10), nullable=False),
        ],
        ["localization_id", "bucket"],
    )
    op.create_index(
        "ix_stats_article_hourly_section_bucket",
        "stats_article_hourly",
        ["section_id", "bucket"],
    )
    _measure_table(
        "stats_article_daily",
        [
            sa.Column("localization_id", sa.Uuid(), nullable=False),
            sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
            sa.Column("article_id", sa.Uuid(), nullable=False),
            sa.Column("section_id", sa.Uuid(), nullable=False),
            sa.Column("locale", sa.String(length=10), nullable=False),
        ],
        ["localization_id", "bucket"],
    )
    op.create_index(
        "ix_stats_article_daily_section_bucket",
        "stats_article_daily",
        ["section_id", "bucket"],
    )
    _measure_table(
        "stats_article_window",
        [
            sa.Column("localization_id", sa.Uuid(), nullable=False),
            sa.Column("window_days", sa.SmallInteger(), nullable=False),
            sa.Column("article_id", sa.Uuid(), nullable=False),
            sa.Column("section_id", sa.Uuid(), nullable=False),
            sa.Column("locale", sa.String(length=10), nullable=False),
        ],
        ["localization_id", "window_days"],
    )
    op.create_index(
        "ix_stats_article_window_section",
        "stats_article_window",
        ["window_days", "section_id"],
    )
    op.create_table(
        "stats_article_referrer_daily",
        sa.Column("localization_id", sa.Uuid(), nullable=False),
        sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("referrer_class", sa.String(length=16), nullable=False),
        sa.Column("views", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint(
            "localization_id", "bucket", "referrer_class", name="pk_stats_article_referrer_daily"
        ),
    )
    _measure_table(
        "stats_site_hourly",
        [
            sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
            sa.Column("surface", sa.String(length=16), nullable=False),
        ],
        ["bucket", "surface"],
    )
    _measure_table(
        "stats_site_daily",
        [
            sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
            sa.Column("surface", sa.String(length=16), nullable=False),
        ],
        ["bucket", "surface"],
    )
    _measure_table(
        "stats_site_window",
        [sa.Column("window_days", sa.SmallInteger(), nullable=False)],
        ["window_days"],
    )
    _measure_table(
        "stats_section_hourly",
        [
            sa.Column("section_id", sa.Uuid(), nullable=False),
            sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        ],
        ["section_id", "bucket"],
    )
    _measure_table(
        "stats_section_daily",
        [
            sa.Column("section_id", sa.Uuid(), nullable=False),
            sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        ],
        ["section_id", "bucket"],
    )
    _measure_table(
        "stats_section_window",
        [
            sa.Column("section_id", sa.Uuid(), nullable=False),
            sa.Column("window_days", sa.SmallInteger(), nullable=False),
        ],
        ["section_id", "window_days"],
    )


def downgrade() -> None:
    for name in (
        "stats_section_window",
        "stats_section_daily",
        "stats_section_hourly",
        "stats_site_window",
        "stats_site_daily",
        "stats_site_hourly",
        "stats_article_referrer_daily",
        "stats_article_window",
        "stats_article_daily",
        "stats_article_hourly",
        "events",
    ):
        op.drop_table(name)


def _measure_table(name: str, keys: list[sa.Column[object]], primary: list[str]) -> None:
    op.create_table(
        name,
        *keys,
        sa.Column("views", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("unique_visitors", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("engaged_ms_sum", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("engaged_views", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("scroll_75", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("clicks", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint(*primary, name=f"pk_{name}"),
    )
