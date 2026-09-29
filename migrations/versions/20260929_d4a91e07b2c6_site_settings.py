"""site settings singleton

Revision ID: d4a91e07b2c6
Revises: c8f14ab20e31
Create Date: 2026-09-29 09:30:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4a91e07b2c6"
down_revision: str | Sequence[str] | None = "c8f14ab20e31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "site_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_name", sa.String(length=120), nullable=False),
        sa.Column(
            "registration_enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_site_settings"),
    )
    op.execute(
        "INSERT INTO site_settings (id, site_name, registration_enabled) VALUES (1, 'Newsroom', true)"
    )


def downgrade() -> None:
    op.drop_table("site_settings")
