"""article devices, click targets, and separate site surfaces

Revision ID: a7c3e91b4d20
Revises: c4e8a1b09d33
Create Date: 2026-10-09 00:20:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e91b4d20"
down_revision: str | Sequence[str] | None = "c4e8a1b09d33"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("tag_id", sa.Uuid(), nullable=True))
    op.drop_constraint("ck_events_surface", "events", type_="check")
    op.create_check_constraint(
        "ck_events_surface",
        "events",
        "surface IN ('article', 'page', 'home', 'section', 'tag', 'search')",
    )
    op.create_table(
        "stats_article_device_daily",
        sa.Column("localization_id", sa.Uuid(), nullable=False),
        sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_class", sa.String(length=16), nullable=False),
        sa.Column("views", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint(
            "localization_id", "bucket", "device_class", name="pk_stats_article_device_daily"
        ),
        sa.CheckConstraint(
            "device_class IN ('desktop', 'mobile', 'tablet', 'other')",
            name="ck_stats_article_device_daily_device_class",
        ),
    )
    op.create_table(
        "stats_article_click_daily",
        sa.Column("localization_id", sa.Uuid(), nullable=False),
        sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("click_target", sa.String(length=200), nullable=False),
        sa.Column("clicks", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint(
            "localization_id", "bucket", "click_target", name="pk_stats_article_click_daily"
        ),
        sa.CheckConstraint("click_target <> ''", name="ck_stats_article_click_daily_click_target"),
    )
    op.drop_table("stats_site_window")
    op.create_table(
        "stats_site_window",
        sa.Column("window_days", sa.SmallInteger(), nullable=False),
        sa.Column("surface", sa.String(length=16), nullable=False),
        sa.Column("views", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("unique_visitors", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("engaged_ms_sum", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("engaged_views", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("scroll_75", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("clicks", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("window_days", "surface", name="pk_stats_site_window"),
    )
    _window("stats_section_listing_window", "section_id")
    _window("stats_page_window", "page_id")
    _window("stats_tag_window", "tag_id")
    op.execute("DELETE FROM stats_site_daily WHERE surface = 'all'")
    op.execute("DELETE FROM stats_site_hourly WHERE surface = 'all'")


def downgrade() -> None:
    op.execute("DELETE FROM stats_site_daily WHERE surface = 'search'")
    op.execute("DELETE FROM stats_site_hourly WHERE surface = 'search'")
    op.drop_table("stats_tag_window")
    op.drop_table("stats_page_window")
    op.drop_table("stats_section_listing_window")
    op.drop_table("stats_site_window")
    op.create_table(
        "stats_site_window",
        sa.Column("window_days", sa.SmallInteger(), nullable=False),
        sa.Column("views", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("unique_visitors", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("engaged_ms_sum", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("engaged_views", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("scroll_75", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("clicks", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("window_days", name="pk_stats_site_window"),
    )
    op.drop_table("stats_article_click_daily")
    op.drop_table("stats_article_device_daily")
    op.drop_constraint("ck_events_surface", "events", type_="check")
    op.create_check_constraint(
        "ck_events_surface",
        "events",
        "surface IN ('article', 'page', 'home', 'section', 'tag')",
    )
    op.drop_column("events", "tag_id")


def _window(name: str, key: str) -> None:
    op.create_table(
        name,
        sa.Column(key, sa.Uuid(), nullable=False),
        sa.Column("window_days", sa.SmallInteger(), nullable=False),
        sa.Column("views", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("unique_visitors", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("engaged_ms_sum", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("engaged_views", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("scroll_75", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("clicks", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint(key, "window_days", name=f"pk_{name}"),
    )
