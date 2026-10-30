"""add transcript speaker names

A person's names for the speakers of a transcription step, kept with its
transcript corrections and in every saved revision of them. A constant
default changes only the catalog: existing rows read '{}' without a rewrite.
The downgrade drops the columns and the names in them.

Revision ID: 202610191005
Revises: 202610151000
Create Date: 2026-10-19 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "202610191005"
down_revision: str | None = "202610151000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("flow_transcript_corrections", "flow_transcript_correction_revisions")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "speaker_names",
                JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table in reversed(_TABLES):
        op.drop_column(table, "speaker_names")
