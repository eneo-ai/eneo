"""Add inline_file_text column to assistants.

Revision ID: 202607262000
Revises: 202607261700
Create Date: 2026-07-26
"""

import sqlalchemy as sa

from alembic import op

revision = "202607262000"
down_revision = "202607261700"
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
