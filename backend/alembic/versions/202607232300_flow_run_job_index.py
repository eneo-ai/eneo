"""Add the measured Flow run job foreign-key support index.

Revision ID: 202607232300_flow_run_job_index
Revises: 202607230130_review_actor_delete
Create Date: 2026-07-23 23:00:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "202607232300_flow_run_job_index"
down_revision = "202607230130_review_actor_delete"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_flow_runs_job_id"
_TABLE_NAME = "flow_runs"
_INDEX_COLUMNS = ("job_id",)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME}
                ON {_TABLE_NAME} ({_INDEX_COLUMNS[0]});
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME};")
