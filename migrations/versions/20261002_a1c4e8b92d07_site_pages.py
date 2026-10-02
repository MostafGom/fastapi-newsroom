"""site pages replace homepage slots

Revision ID: a1c4e8b92d07
Revises: e3b71c9a04f5
Create Date: 2026-10-02 20:10:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1c4e8b92d07"
down_revision: str | Sequence[str] | None = "e3b71c9a04f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("homepage_slots")
    op.create_table(
        "pages",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pages")),
        sa.UniqueConstraint("key", name=op.f("uq_pages_key")),
    )
    op.create_table(
        "page_translations",
        sa.Column("page_id", sa.Uuid(), nullable=False),
        sa.Column("locale", sa.String(length=10), nullable=False),
        sa.Column("slug", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("status", sa.Enum("draft", "published", name="page_status"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["locale"],
            ["locales.code"],
            name=op.f("fk_page_translations_locale_locales"),
        ),
        sa.ForeignKeyConstraint(
            ["page_id"],
            ["pages.id"],
            name=op.f("fk_page_translations_page_id_pages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_page_translations")),
        sa.UniqueConstraint("locale", "slug", name=op.f("uq_page_translations_locale_slug")),
        sa.UniqueConstraint("page_id", "locale", name=op.f("uq_page_translations_page_id_locale")),
    )


def downgrade() -> None:
    op.drop_table("page_translations")
    op.drop_table("pages")
    sa.Enum(name="page_status").drop(op.get_bind(), checkfirst=True)
    op.create_table(
        "homepage_slots",
        sa.Column("locale", sa.String(length=10), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("localization_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(
            ["locale"], ["locales.code"], name=op.f("fk_homepage_slots_locale_locales")
        ),
        sa.ForeignKeyConstraint(
            ["localization_id"],
            ["article_localizations.id"],
            name=op.f("fk_homepage_slots_localization_id_article_localizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("locale", "position", name=op.f("pk_homepage_slots")),
        sa.UniqueConstraint(
            "locale", "localization_id", name=op.f("uq_homepage_slots_locale_localization_id")
        ),
    )
