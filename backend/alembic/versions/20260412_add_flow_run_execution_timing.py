"""add execution timing to flow_runs and flow_step_results

Revision ID: 20260412_flow_exec_timing
Revises: 20260411_flow_run_identity
Create Date: 2026-04-12 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "20260412_flow_exec_timing"
down_revision = "20260411_flow_run_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flow_runs",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "flow_runs",
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "flow_step_results",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "flow_step_results",
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("flow_step_results", "finished_at")
    op.drop_column("flow_step_results", "started_at")
    op.drop_column("flow_runs", "finished_at")
    op.drop_column("flow_runs", "started_at")
