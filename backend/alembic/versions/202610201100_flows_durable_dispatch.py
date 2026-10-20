"""flows durable dispatch

Flow runs are durable jobs: the redispatch cron's partial index on ``jobs``
must cover ``run_flow`` as well. Also seeds the ``flows_core`` tenant feature
flag (off by default; tenants opt in).

Revision ID: 202610201100
Revises: 202610201000
Create Date: 2026-10-20 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "202610201100"
down_revision: str | None = "202610201000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_jobs_durable_dispatch"


def _recreate_dispatch_index(tasks: str) -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY {_INDEX}
            ON jobs (dispatch_attempted_at ASC NULLS FIRST, id ASC)
            WHERE status = 'queued'
              AND dispatch_envelope IS NOT NULL
              AND task IN ({tasks})
            """
        )


def upgrade() -> None:
    _recreate_dispatch_index("'upload_info_blob', 'transcription', 'run_flow'")
    op.execute("""
        INSERT INTO global_feature_flags (id, name, description, enabled, created_at, updated_at)
        VALUES (
            gen_random_uuid(),
            'flows_core',
            'Flows: chat-authored, deterministic multi-step runs per space',
            false,
            now(),
            now()
        )
        ON CONFLICT (name) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM tenant_feature_flags WHERE name = 'flows_core'")
    op.execute("DELETE FROM global_feature_flags WHERE name = 'flows_core'")
    _recreate_dispatch_index("'upload_info_blob', 'transcription'")
