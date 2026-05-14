"""idx_active_crawl_lookup

Revision ID: 202605142300
Revises: 202605141700
Create Date: 2026-05-14 23:00:00.000000

Adds indexes for the active crawl duplicate guard used at worker startup.
The indexes are created concurrently so large historical crawl tables are not
locked during production rollout.

If a deployment is interrupted while PostgreSQL is building these concurrent
indexes, operators should drop the invalid index concurrently and rerun the
migration. `IF NOT EXISTS` is kept for normal deploy idempotency, not invalid
index repair.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "202605142300"
down_revision: Union[str, None] = "202605141700"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JOBS_ACTIVE_INDEX = "idx_jobs_active_crawl_created_at_id"
CRAWL_RUNS_WEBSITE_JOB_INDEX = "idx_crawl_runs_website_job_lookup"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {JOBS_ACTIVE_INDEX}
            ON jobs (created_at, id)
            WHERE task = 'crawl' AND status IN ('queued', 'in progress')
            """
        )
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {CRAWL_RUNS_WEBSITE_JOB_INDEX}
            ON crawl_runs (website_id, job_id)
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"DROP INDEX CONCURRENTLY IF EXISTS {CRAWL_RUNS_WEBSITE_JOB_INDEX}"
        )
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {JOBS_ACTIVE_INDEX}")
