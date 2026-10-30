"""Index a user's jobs by creation time for the jobs poll

Every open app tab polls GET /api/v1/jobs/, which reads one user's recent jobs
(``user_id = :u AND created_at >= now() - 7 days``, ordered by created_at). No
index held jobs by user, so each poll scanned the whole table, which only grows.
``ix_jobs_user_created`` serves the poll and the ``users.id`` ON DELETE CASCADE.

Measured on PostgreSQL 16 with 203k jobs for 500 users: a busy user's poll went
from 6.9 ms (parallel sequential scan and sort, 2,906 buffers) to 0.09 ms
(59 buffers), a typical user's from 6.5 ms to 0.01 ms (9 buffers). The index
costs about 40 MB per million jobs.

The index is built ``CONCURRENTLY`` (no write lock on jobs). A failed build can
leave it INVALID; a rerun drops that leftover before building it again and
keeps an index already built.

Revision ID: 202610261000
Revises: 202610251100
Create Date: 2026-10-26 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610261000"
down_revision: str | None = "202610251100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_jobs_user_created"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            valid = (
                op.get_bind()
                .execute(
                    sa.text(
                        "SELECT indisvalid FROM pg_index "
                        "WHERE indexrelid = to_regclass(:name)"
                    ),
                    {"name": _INDEX},
                )
                .scalar()
            )
            if valid is False:
                op.execute(f"DROP INDEX CONCURRENTLY {_INDEX}")
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} "
                "ON jobs (user_id, created_at)"
            )
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        finally:
            op.execute("RESET lock_timeout")
