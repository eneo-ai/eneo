"""add_flow_run_trace_and_attempt_provenance

Add run-level trace correlation and attempt-level provenance fields to support
enterprise flow evidence, export, and future observability adapters.

Revision ID: 202603311430
Revises: 202603121400
Create Date: 2026-03-31 14:30:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202603311430"
down_revision = "202603121400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flow_runs",
        sa.Column(
            "trace_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
    )
    op.create_index("ix_flow_runs_trace_id", "flow_runs", ["trace_id"], unique=False)

    op.add_column(
        "flow_step_attempts",
        sa.Column("requested_model", sa.String(), nullable=True),
    )
    op.add_column(
        "flow_step_attempts",
        sa.Column("response_model", sa.String(), nullable=True),
    )
    op.add_column(
        "flow_step_attempts",
        sa.Column("provider", sa.String(), nullable=True),
    )
    op.add_column(
        "flow_step_attempts",
        sa.Column("finish_reason", sa.String(), nullable=True),
    )
    op.add_column(
        "flow_step_attempts",
        sa.Column("provider_response_id", sa.String(), nullable=True),
    )
    op.add_column(
        "flow_step_attempts",
        sa.Column("num_tokens_input", sa.Integer(), nullable=True),
    )
    op.add_column(
        "flow_step_attempts",
        sa.Column("num_tokens_output", sa.Integer(), nullable=True),
    )
    op.add_column(
        "flow_step_attempts",
        sa.Column("provenance_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("flow_step_attempts", "provenance_json")
    op.drop_column("flow_step_attempts", "num_tokens_output")
    op.drop_column("flow_step_attempts", "num_tokens_input")
    op.drop_column("flow_step_attempts", "provider_response_id")
    op.drop_column("flow_step_attempts", "finish_reason")
    op.drop_column("flow_step_attempts", "provider")
    op.drop_column("flow_step_attempts", "response_model")
    op.drop_column("flow_step_attempts", "requested_model")

    op.drop_index("ix_flow_runs_trace_id", table_name="flow_runs")
    op.drop_column("flow_runs", "trace_id")
