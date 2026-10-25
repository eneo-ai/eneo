"""Index the run list's status count for one starter

A member and a service key list only their own runs, and every first page of
the list counts those runs by status. The listing indexes of 202610241000 hold
a starter's runs in start order but not their status, so that count read the
heap, or the whole table for a starter with many runs.
``ix_flow_runs_flow_user_status`` and ``ix_flow_runs_flow_service_status`` add
the status per starter, so the count reads the index alone.

Measured on PostgreSQL 16 with 1M runs (600k in one flow), best of 5, at
202610241000 after VACUUM FULL and at this revision after a plain VACUUM:

- Unsearched counts: a heavy member's went from 60.6 ms (sequential scan, 90k
  buffers) to 7.9 ms (index-only scan, 142 buffers); a light, typical or
  churned member's and a service key's from 6-10 ms (index scan reading the
  heap, 10-16k buffers) to 0.5-0.9 ms (20-28 buffers). The admin count does
  not use these indexes; it went from 69 to 44 ms because the plain VACUUM
  let it read ix_flow_runs_flow_listing alone.
- Searched counts: the planner now starts a member's or a service key's from
  these indexes too. Most are about even (21-29 ms), but the heavy member's
  went from 265 ms / 77k buffers to 306 ms / 86k buffers (+16 %). The admin's
  keeps its plan (498 -> 434 ms).

An earlier run measured, after 60k run lifecycles and a plain VACUUM, the heavy
member's unsearched count at 102 -> 8.3 ms. Cost: 7.3 MB and 0.4 MB of index;
15k-lifecycle write batches took the same time within noise.

Each index is built ``CONCURRENTLY`` (no write lock on flow_runs). A failed
build can leave the index INVALID; a rerun drops that leftover before building
it again and keeps the index already built. To inspect a failed build:

    SELECT indexrelid::regclass, indisvalid FROM pg_index
    WHERE indrelid = 'flow_runs'::regclass AND NOT indisvalid;

Revision ID: 202610241100
Revises: 202610241000
Create Date: 2026-10-24 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610241100"
down_revision: str | None = "202610241000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = (
    (
        "ix_flow_runs_flow_user_status",
        "(tenant_id, flow_id, principal_user_id, status) "
        "WHERE principal_user_id IS NOT NULL",
    ),
    (
        "ix_flow_runs_flow_service_status",
        "(tenant_id, flow_id, principal_service_id, status) "
        "WHERE principal_service_id IS NOT NULL",
    ),
)


def _create(name: str, definition: str) -> None:
    valid = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)"
            ),
            {"name": name},
        )
        .scalar()
    )
    if valid is False:
        op.execute(f"DROP INDEX CONCURRENTLY {name}")
    op.execute(
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON flow_runs {definition}"
    )


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            for name, definition in _INDEXES:
                _create(name, definition)
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            for name, _definition in reversed(_INDEXES):
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
        finally:
            op.execute("RESET lock_timeout")
