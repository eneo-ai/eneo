"""Index the marked Flow runs per flow by retention anchor

The automatic removal and its health probe read only marked runs
(``started_under_space_retention IS TRUE``) whose flow's space has a time,
oldest anchor first. Without this index they read the organisation's terminal
runs, including the history from before the upgrade that is never marked; when
the planner expects one flow and loops over each, it reads them once per flow.
The predicate holds only the mark: the statements send the statuses as bind
parameters, and a generic plan cannot match a partial index on a parameter.

Measured on PostgreSQL 16, 23 flows, 400k unmarked runs: with 1k marked runs
and none due the probe took 7 ms to 3.8 s without the index, depending on the
plan picked (the slow ones under default statistics for flows and spaces),
and 0.3-0.9 ms with it. The worst probe or selection in any measured state
was 8.5 s and 27 s in two passes without it, 0.32 s and 0.44 s with it (the
second pass on a loaded machine). With a backlog of
due runs and full statistics the planner keeps its sequential plan (74 ms per
selection, as before). Ordered by anchor alone the index was faster there but
unused under default statistics (8.6 s), so it was not chosen. Cost: 22 MB
for 302k marked runs beside a 144 MB heap; unmarked runs are not in it.

Built ``CONCURRENTLY`` (no write lock on flow_runs). A failed build can leave
the index INVALID; a rerun drops that leftover before building it again.

Revision ID: 202611241100
Revises: 202611241000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202611241100"
down_revision: str | None = "202611241000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "ix_flow_runs_marked_flow_retention_anchor"
_DEFINITION = (
    "(flow_id, (coalesce(finished_at, created_at)), id) INCLUDE (tenant_id) "
    "WHERE started_under_space_retention IS TRUE"
)


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
                    {"name": _NAME},
                )
                .scalar()
            )
            if valid is False:
                op.execute(f"DROP INDEX CONCURRENTLY {_NAME}")
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_NAME} "
                f"ON flow_runs {_DEFINITION}"
            )
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_NAME}")
        finally:
            op.execute("RESET lock_timeout")
