"""search documents

Revision ID: b7e2c1a94f08
Revises: 4896c58355f9
Create Date: 2026-09-29 08:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7e2c1a94f08"
down_revision: str | Sequence[str] | None = "4896c58355f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "search_documents",
        sa.Column("localization_id", sa.Uuid(), nullable=False),
        sa.Column("locale", sa.String(length=10), nullable=False),
        sa.Column("slug", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("excerpt", sa.String(length=1000), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("section_slug", sa.String(length=160), nullable=False),
        sa.Column("section_name", sa.String(length=120), nullable=False),
        sa.Column("tag_slugs", postgresql.ARRAY(sa.String(length=160)), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("document", postgresql.TSVECTOR(), nullable=False),
        sa.ForeignKeyConstraint(
            ["localization_id"],
            ["article_localizations.id"],
            name=op.f("fk_search_documents_localization_id_article_localizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("localization_id", name=op.f("pk_search_documents")),
    )
    op.create_index(
        "ix_search_documents_document",
        "search_documents",
        ["document"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_search_documents_recent",
        "search_documents",
        ["locale", "published_at", "localization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_search_documents_recent", table_name="search_documents")
    op.drop_index("ix_search_documents_document", table_name="search_documents")
    op.drop_table("search_documents")
