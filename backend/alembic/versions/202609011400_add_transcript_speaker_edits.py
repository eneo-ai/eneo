"""add transcript speaker edits

Revision ID: 202609011400
Revises: 202609011000
Create Date: 2026-09-01 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "202609011400"
down_revision: str | None = "202609011000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "flow_transcript_corrections",
        sa.Column(
            "speaker_edits_json",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("flow_transcript_corrections", "speaker_edits_json")
