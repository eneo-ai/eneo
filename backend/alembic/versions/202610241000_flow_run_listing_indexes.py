"""Index a flow's run list in its started_at order

A run list filters one flow's runs and orders them by start time (the
creation time while a run has not started), then creation time and id; the
web run list asks for that order by default and polls it while runs are
active. ``ix_flow_runs_flow_listing`` holds that order, so a page is read in
index order, and INCLUDEs status, so the list's status count reads the index
alone. Members and service keys list only their own runs, which the two
partial indexes hold per starter. ``ix_flow_runs_flow_id`` is a strict prefix
of ``ix_flow_runs_flow_id_status`` and goes.

Measured on PostgreSQL 16 with 305k runs (200k in one flow), LIMIT 26, warm:
the admin started_at page went from 36.6 ms / 27,328 buffers (parallel
sequential scan and sort) to 0.04 ms / 26 buffers; the status count from
29.9 ms to 15.0 ms (index-only scan). Own-run started_at pages read 7-28
buffers instead of up to 25k; for a starter whose runs are few or old in a busy
flow the flow index alone would read 39k. The plans stayed the same under
generic (prepared statement) plans. Status and duration sorts are unchanged.
Cost there: flow_runs indexes +62% (99 -> 161 MB), a 10k-row bulk insert +11%,
its WAL +22%.

Each index is built ``CONCURRENTLY`` (no write lock on flow_runs) before the
old one is dropped, also on downgrade. A failed build can leave the index
INVALID; a rerun drops that leftover before building it again and keeps the
indexes already built. To inspect a failed build:

    SELECT indexrelid::regclass, indisvalid FROM pg_index
    WHERE indrelid = 'flow_runs'::regclass AND NOT indisvalid;

Revision ID: 202610241000
Revises: 202610231100
Create Date: 2026-10-24 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610241000"
down_revision: str | None = "202610231100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copy of the started_at order in ``run_list_order``.
_LISTING_ORDER = "coalesce(started_at, created_at) DESC, created_at DESC, id DESC"
_INDEXES = (
    (
        "ix_flow_runs_flow_listing",
        f"(tenant_id, flow_id, {_LISTING_ORDER}) INCLUDE (status)",
    ),
    (
        "ix_flow_runs_flow_user_listing",
        f"(tenant_id, flow_id, principal_user_id, {_LISTING_ORDER}) "
        "WHERE principal_user_id IS NOT NULL",
    ),
    (
        "ix_flow_runs_flow_service_listing",
        f"(tenant_id, flow_id, principal_service_id, {_LISTING_ORDER}) "
        "WHERE principal_service_id IS NOT NULL",
    ),
)
_REPLACED_INDEX = ("ix_flow_runs_flow_id", "(flow_id)")


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
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_REPLACED_INDEX[0]}")
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            _create(*_REPLACED_INDEX)
            for name, _definition in reversed(_INDEXES):
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
        finally:
            op.execute("RESET lock_timeout")
