"""Index stale jobs and app run notifications on the 2.3 release line.

Build both indexes concurrently so API and worker writes can continue.

Revision ID: 202611201300
Revises: 202610261200
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611201300"
down_revision: str | None = "202610261200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = {
    "ix_jobs_active_task_updated_id": (
        "ON jobs (task, updated_at, id) WHERE status IN ('queued', 'in progress')"
    ),
    "ix_app_runs_job_id": "ON app_runs (job_id)",
}


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # A concurrent build can wait for the transaction of an active app run.
        for name, definition in _INDEXES.items():
            valid = (
                op.get_bind()
                .execute(
                    sa.text(
                        "SELECT indisvalid FROM pg_index "
                        "WHERE indexrelid = to_regclass(:name)"
                    ),
                    {"name": name},
                )
                .scalar()
            )
            # Interrupted concurrent builds can leave invalid indexes.
            if valid is False:
                op.execute(f"DROP INDEX CONCURRENTLY {name}")
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} {definition}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name in _INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
