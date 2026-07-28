"""add durable job dispatch state

Revision ID: 202607281600
Revises: 202607281340
Create Date: 2026-07-28 16:00:00.000000

The partial index is built concurrently so upgrades do not block job writes.
If a build fails, rerun the migration: column creation is idempotent and the
explicit concurrent drop removes any invalid index before retrying.
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
        if_not_exists=True,
    )
    op.add_column(
        "jobs",
        sa.Column(
            "dispatch_attempted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        if_not_exists=True,
    )
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY {_INDEX}
            ON jobs (dispatch_attempted_at ASC NULLS FIRST, id ASC)
            WHERE status = 'queued'
              AND dispatch_envelope IS NOT NULL
              AND task IN ('upload_info_blob', 'transcription')
            """
        )


def downgrade() -> None:
    pending_count = int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT count(*)
                FROM jobs
                WHERE dispatch_envelope IS NOT NULL
                  AND status IN ('queued', 'in progress')
                  AND task IN ('upload_info_blob', 'transcription')
                """
            )
        )
        .scalar_one()
    )
    if pending_count:
        raise RuntimeError(
            "Cannot downgrade durable job dispatch while "
            f"{pending_count} queued or in-progress envelope jobs remain. "
            "Drain them or explicitly fail them before retrying."
        )

    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
    op.drop_column("jobs", "dispatch_attempted_at")
    op.drop_column("jobs", "dispatch_envelope")
