"""add flow runs tenant flow created_at index

One flow's runs are read newest first: the run list of a flow (sorted by
creation time, the default) and the newest finished runs the flow
suggestions measure. ``ix_flow_runs_tenant_created_at`` orders a whole
tenant's runs and ``ix_flow_runs_flow_id_status`` has no order, so both reads
sorted every run of the flow, and their cost grew with its history. This index
orders each flow's runs by creation time and id, so a read of N runs scans N
index entries backwards.

``CONCURRENTLY`` avoids a write lock on ``flow_runs`` during the build. It can
leave the index INVALID if the build fails. A retry drops that index before
building it again. To inspect a failed build:

    SELECT indexrelid::regclass, indisvalid FROM pg_index
    WHERE indexrelid::regclass::text = 'ix_flow_runs_tenant_flow_created_at';
    -- if indisvalid = false, run the upgrade statements by hand.

Revision ID: 202610251000
Revises: 202610231100
Create Date: 2026-10-25 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202610251000"
down_revision: str | None = "202610231100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_flow_runs_tenant_flow_created_at"
_TABLE = "flow_runs"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            op.drop_index(
                _INDEX, table_name=_TABLE, if_exists=True, postgresql_concurrently=True
            )
            op.create_index(
                _INDEX,
                _TABLE,
                ["tenant_id", "flow_id", "created_at", "id"],
                postgresql_concurrently=True,
            )
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            op.drop_index(
                _INDEX, table_name=_TABLE, if_exists=True, postgresql_concurrently=True
            )
        finally:
            op.execute("RESET lock_timeout")
