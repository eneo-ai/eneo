"""add source_metadata to info_blobs

Revision ID: 202610011000
Revises: 202609291000
Create Date: 2026-10-01 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202610011000"
down_revision: str = "202609291000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ordered list of {name, label, value, kind} entries describing the source
    # system's own document properties (SharePoint library columns). NULL for
    # documents whose source has no such properties.
    op.add_column(
        "info_blobs",
        sa.Column(
            "source_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("info_blobs", "source_metadata")
