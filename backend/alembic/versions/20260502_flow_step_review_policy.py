"""Add flow step review policy.

Revision ID: 20260502_flow_step_review_policy
Revises: 20260502_review_checkpoints
Create Date: 2026-05-02 17:10:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260502_flow_step_review_policy"
down_revision = "20260502_review_checkpoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "flow_steps",
        sa.Column("review_policy", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("flow_steps", "review_policy")
