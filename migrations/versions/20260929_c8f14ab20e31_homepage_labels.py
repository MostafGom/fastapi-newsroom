"""homepage slot labels

Revision ID: c8f14ab20e31
Revises: 6252d3aa14cf
Create Date: 2026-09-29 09:10:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8f14ab20e31"
down_revision: str | Sequence[str] | None = "6252d3aa14cf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("homepage_slots", sa.Column("label", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("homepage_slots", "label")
