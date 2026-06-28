"""add planning state columns to builder_sessions

Revision ID: 20260423_builder_planning_state
Revises: 20260421_builder_conv_msg_id
Create Date: 2026-04-23 00:00:00.000000

Backs persisted planning state for AI Builder sessions:
- planning_state_jsonb: the full serialized PlanningState blob
- planning_state_version: optimistic-concurrency counter (default 0)
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20260423_builder_planning_state"
down_revision = "20260421_builder_conv_msg_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "builder_sessions",
        sa.Column("planning_state_jsonb", JSONB, nullable=True),
    )
    op.add_column(
        "builder_sessions",
        sa.Column(
            "planning_state_version",
            sa.BigInteger,
            nullable=False,
            server_default="0",
        ),
    )

def downgrade() -> None:
    op.drop_column("builder_sessions", "planning_state_version")
    op.drop_column("builder_sessions", "planning_state_jsonb")
