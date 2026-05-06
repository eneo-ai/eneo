"""Add optional per-step flow runtime timeout."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260506_flow_step_timeout"
down_revision = "20260502_drop_result_tool_calls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flow_steps",
        sa.Column("timeout_seconds", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_flow_steps_timeout_seconds_positive",
        "flow_steps",
        "timeout_seconds IS NULL OR timeout_seconds > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_flow_steps_timeout_seconds_positive",
        "flow_steps",
        type_="check",
    )
    op.drop_column("flow_steps", "timeout_seconds")
