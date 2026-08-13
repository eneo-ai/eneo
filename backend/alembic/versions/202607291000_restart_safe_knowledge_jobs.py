"""add restart-safe knowledge job recovery state

Revision ID: 202607291000
Revises: 202607281600
Create Date: 2026-07-29 10:00:00.000000

Both partial indexes are built concurrently so upgrades do not block job
writes. Failed builds are safe to retry because invalid indexes are dropped
before each build. Downgrade locks job writers so the cleanup-state guard and
destructive DDL run atomically.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607291000"
down_revision: str | None = "202607281600"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REAPER_INDEX = "ix_jobs_knowledge_in_progress_reaper"
_CLEANUP_INDEX = "ix_jobs_staging_cleanup"


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "staging_cleaned_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        if_not_exists=True,
    )
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_REAPER_INDEX}")
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY {_REAPER_INDEX}
            ON jobs (updated_at ASC, id ASC)
            WHERE status = 'in progress'
              AND task IN ('upload_info_blob', 'transcription')
            """
        )
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_CLEANUP_INDEX}")
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY {_CLEANUP_INDEX}
            ON jobs (finished_at ASC NULLS FIRST, id ASC)
            WHERE dispatch_envelope IS NOT NULL
              AND status IN ('complete', 'failed')
              AND staging_cleaned_at IS NULL
            """
        )


def downgrade() -> None:
    op.execute("LOCK TABLE jobs IN ACCESS EXCLUSIVE MODE")
    uncleaned_count = int(
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT count(*)
                FROM jobs
                WHERE dispatch_envelope IS NOT NULL
                  AND status IN ('complete', 'failed')
                  AND staging_cleaned_at IS NULL
                """
            )
        )
        .scalar_one()
    )
    if uncleaned_count:
        raise RuntimeError(
            "Cannot downgrade restart-safe knowledge jobs while "
            f"{uncleaned_count} terminal envelope jobs remain uncleaned. "
            "Reconcile their staged files before retrying."
        )

    op.execute(f"DROP INDEX IF EXISTS {_CLEANUP_INDEX}")
    op.execute(f"DROP INDEX IF EXISTS {_REAPER_INDEX}")
    op.drop_column("jobs", "staging_cleaned_at")
