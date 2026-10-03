"""remember who last reviewed or published an edition

Revision ID: b6e1d4c80a12
Revises: a1c4e8b92d07
Create Date: 2026-10-03 09:10:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6e1d4c80a12"
down_revision: str | Sequence[str] | None = "a1c4e8b92d07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("article_localizations", sa.Column("reviewed_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_article_localizations_reviewed_by_users"),
        "article_localizations",
        "users",
        ["reviewed_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_article_localizations_reviewed_by"),
        "article_localizations",
        ["reviewed_by"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_article_localizations_reviewed_by"), table_name="article_localizations")
    op.drop_constraint(
        op.f("fk_article_localizations_reviewed_by_users"),
        "article_localizations",
        type_="foreignkey",
    )
    op.drop_column("article_localizations", "reviewed_by")
