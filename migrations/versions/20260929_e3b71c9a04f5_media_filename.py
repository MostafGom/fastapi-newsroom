"""display name for a media file

Revision ID: e3b71c9a04f5
Revises: d4a91e07b2c6
Create Date: 2026-09-29 19:25:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3b71c9a04f5"
down_revision: str | Sequence[str] | None = "d4a91e07b2c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("media_assets", sa.Column("filename", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("media_assets", "filename")
