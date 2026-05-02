"""Add rerun runtime lineage constraints.

Revision ID: 20260502_rerun_runtime_lineage
Revises: 20260502_rerun_ops
Create Date: 2026-05-02 15:50:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "20260502_rerun_runtime_lineage"
down_revision = "20260502_rerun_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flow_run_audit_outbox",
        sa.Column("run_revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.drop_constraint(
        "uq_flow_run_audit_outbox_run",
        "flow_run_audit_outbox",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_flow_run_audit_outbox_run_revision",
        "flow_run_audit_outbox",
        ["flow_run_id", "run_revision"],
    )
    op.create_index(
        "uq_flow_run_rerun_operations_one_active_per_run",
        "flow_run_rerun_operations",
        ["flow_run_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_flow_run_rerun_operations_one_active_per_run",
        table_name="flow_run_rerun_operations",
    )
    op.drop_constraint(
        "uq_flow_run_audit_outbox_run_revision",
        "flow_run_audit_outbox",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_flow_run_audit_outbox_run",
        "flow_run_audit_outbox",
        ["flow_run_id"],
    )
    op.drop_column("flow_run_audit_outbox", "run_revision")
