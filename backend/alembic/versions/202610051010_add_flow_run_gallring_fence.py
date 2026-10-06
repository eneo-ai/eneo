"""add the Flow run deletion fence and the K4 due index

Revision ID: 202610051010
Revises: 202610051000
Create Date: 2026-10-05 10:10:00.000000

flow_runs.gallring_receipt_id (nullable, no default: a catalog-only change) is
set when a run's deletion starts; run readers treat a fenced run as deleted.
ix_flow_runs_flow_gallring_due serves the per-Flow due selection of terminal,
unfenced runs from a literal cutoff. The index is built CONCURRENTLY so writes
continue; a build that fails leaves an INVALID index and no version stamp, and
the next upgrade drops the leftover and builds it again. Offline it emits the
static DDL.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610051010"
down_revision: str = "202610051000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_flow_runs_flow_gallring_due"
_PREDICATE = (
    "status IN ('completed', 'failed', 'cancelled') AND gallring_receipt_id IS NULL"
)


def _index_is_invalid() -> bool:
    valid = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)"
            ),
            {"name": _INDEX},
        )
        .scalar()
    )
    return valid is False


def upgrade() -> None:
    offline = op.get_context().as_sql
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            op.execute(
                "ALTER TABLE flow_runs ADD COLUMN IF NOT EXISTS gallring_receipt_id uuid"
            )
            if not offline and _index_is_invalid():
                op.drop_index(
                    _INDEX, table_name="flow_runs", postgresql_concurrently=True
                )
            op.create_index(
                _INDEX,
                "flow_runs",
                ["flow_id", sa.text("coalesce(finished_at, created_at)"), "id"],
                postgresql_where=sa.text(_PREDICATE),
                postgresql_concurrently=True,
                if_not_exists=True,
            )
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    if not op.get_context().as_sql:
        fenced = (
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT EXISTS (SELECT 1 FROM flow_runs "
                    "WHERE gallring_receipt_id IS NOT NULL)"
                )
            )
            .scalar()
        )
        if fenced:
            raise RuntimeError(
                "Cannot downgrade 202610051010: Flow runs are being deleted "
                "(gallring_receipt_id is set); dropping the fence would show them "
                "partly deleted. Let the nightly task finish them first."
            )
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            op.drop_index(
                _INDEX,
                table_name="flow_runs",
                postgresql_concurrently=True,
                if_exists=True,
            )
            op.execute(
                "ALTER TABLE flow_runs DROP COLUMN IF EXISTS gallring_receipt_id"
            )
        finally:
            op.execute("RESET lock_timeout")
