"""Add admin-set display_name to mcp_server_tools

An admin can rename how an MCP tool is presented (e.g. "tavily_search" ->
"Webbsökning"). Display-only: the protocol-level tool name is untouched, and
tool sync never writes this column.

Revision ID: 202607101002
Revises: 202607101001
Create Date: 2026-07-10

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "202607101002"
down_revision = "202607101001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_server_tools",
        sa.Column("display_name", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_server_tools", "display_name")
