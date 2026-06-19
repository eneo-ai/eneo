"""Add title column to mcp_server_tools.

Revision ID: 202605251000
Revises: 202605201000
Create Date: 2025-06-25
"""

import sqlalchemy as sa

from alembic import op

revision = "202605251000"
down_revision = "202605201000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_server_tools",
        sa.Column("title", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_server_tools", "title")
