"""Add knowledge_mode column to assistants.

Revision ID: 202607061000
Revises: 202607262000
Create Date: 2026-07-06
"""

import sqlalchemy as sa

from alembic import op

revision = "202607061000"
down_revision = "202607262000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Backwards-compatible rollout: existing assistants stay on legacy
    # retrieve-and-inject until an administrator explicitly enables tool mode.
    op.add_column(
        "assistants",
        sa.Column(
            "knowledge_mode",
            sa.String(),
            nullable=False,
            server_default="inject",
        ),
    )


def downgrade() -> None:
    op.drop_column("assistants", "knowledge_mode")
