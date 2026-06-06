"""Add inline_file_text column to assistants.

Revision ID: 202606061002
Revises: 202606061001
Create Date: 2026-06-06
"""

import sqlalchemy as sa

from alembic import op

revision = "202606061002"
down_revision = "202606061001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assistants",
        sa.Column(
            "inline_file_text",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )


def downgrade() -> None:
    op.drop_column("assistants", "inline_file_text")
