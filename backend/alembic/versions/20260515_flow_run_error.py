"""Add structured flow run error payload.

Drop the unpublished run-level error_message mirror so new Flow run state has
one persisted terminal error contract.

Revision ID: 20260515_flow_run_error
Revises: 20260514_review_expiry
Create Date: 2026-05-15 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260515_flow_run_error"
down_revision = "20260514_review_expiry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flow_runs",
        sa.Column("error_json", postgresql.JSONB(), nullable=True),
    )
    op.drop_column("flow_runs", "error_message")


def downgrade() -> None:
    op.add_column(
        "flow_runs",
        sa.Column("error_message", sa.String(), nullable=True),
    )
    op.drop_column("flow_runs", "error_json")
