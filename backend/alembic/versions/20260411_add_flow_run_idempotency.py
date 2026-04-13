"""add flow run idempotency columns

Revision ID: 20260411_flow_run_idempotency
Revises: 20260411_merge_scope_flow_heads
Create Date: 2026-04-11 13:05:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "20260411_flow_run_idempotency"
down_revision = "20260411_merge_scope_flow_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flow_runs",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "flow_runs",
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "uq_flow_runs_idempotency_key",
        "flow_runs",
        ["tenant_id", "flow_id", "user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_flow_runs_idempotency_key", table_name="flow_runs")
    op.drop_column("flow_runs", "request_fingerprint")
    op.drop_column("flow_runs", "idempotency_key")
