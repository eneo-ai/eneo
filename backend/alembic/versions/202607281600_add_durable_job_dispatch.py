"""add durable job dispatch state

Revision ID: 202607281600
Revises: 202607281340
Create Date: 2026-07-28 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202607281600"
down_revision: str | None = "202607281340"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_jobs_durable_dispatch"


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("dispatch_envelope", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "dispatch_attempted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute(
        f"""
        CREATE INDEX {_INDEX}
        ON jobs (dispatch_attempted_at ASC NULLS FIRST, id ASC)
        WHERE status = 'queued'
          AND dispatch_envelope IS NOT NULL
          AND task IN ('upload_info_blob', 'transcription')
        """
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="jobs")
    op.drop_column("jobs", "dispatch_attempted_at")
    op.drop_column("jobs", "dispatch_envelope")
