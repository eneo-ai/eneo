"""add_meta_to_mcp_server_tools

Revision ID: 20260212_add_tool_meta
Revises: rename_integration_perm
Create Date: 2026-02-12 10:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic
revision = "20260212_add_tool_meta"
down_revision = "rename_integration_perm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_server_tools",
        sa.Column("meta", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_server_tools", "meta")
