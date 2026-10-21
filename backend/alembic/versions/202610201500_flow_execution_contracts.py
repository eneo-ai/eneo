"""Principal-scoped run idempotency and pinned execution bindings.

Revision ID: 202610201500
Revises: 202610201400
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "202610201500"
down_revision = "202610201400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flow_versions", sa.Column("runtime_bindings", JSONB(), nullable=True)
    )
    op.add_column("flow_runs", sa.Column("runtime_bindings", JSONB(), nullable=True))
    op.drop_constraint("uq_flow_runs_flow_idempotency_key", "flow_runs", type_="unique")
    for kind in ("user", "service"):
        column = f"principal_{kind}_id"
        op.create_index(
            f"uq_flow_runs_{kind}_idempotency",
            "flow_runs",
            ["flow_id", column, "idempotency_key"],
            unique=True,
            postgresql_where=sa.text(
                f"{column} IS NOT NULL AND idempotency_key IS NOT NULL"
            ),
        )


def downgrade() -> None:
    # Refuse the downgrade if different principals reused a key. An operator
    # must resolve those collisions explicitly; never discard idempotency data.
    op.create_unique_constraint(
        "uq_flow_runs_flow_idempotency_key", "flow_runs", ["flow_id", "idempotency_key"]
    )
    for kind in ("user", "service"):
        op.drop_index(f"uq_flow_runs_{kind}_idempotency", table_name="flow_runs")
    op.drop_column("flow_runs", "runtime_bindings")
    op.drop_column("flow_versions", "runtime_bindings")
