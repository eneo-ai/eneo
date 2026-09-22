"""Add per-attachment inline_text mode to assistants_files.

Revision ID: 202609221000
Revises: 202609161000
Create Date: 2026-09-22
"""

import sqlalchemy as sa

from alembic import op

revision = "202609221000"
down_revision = "202609161000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assistants_files",
        sa.Column(
            "inline_text",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )


def downgrade() -> None:
    op.drop_column("assistants_files", "inline_text")
