"""Add administrator-controlled MCP tool catalog limits.

Revision ID: 202607211200
Revises: 202606061000
Create Date: 2026-07-21
"""

import sqlalchemy as sa

from alembic import op

revision = "202607211200"
down_revision = "202606061000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column(
            "tool_catalog_max_bytes",
            sa.Integer(),
            nullable=False,
            server_default=str(16 * 1024 * 1024),
        ),
    )
    op.add_column(
        "mcp_servers",
        sa.Column(
            "tool_catalog_max_count",
            sa.Integer(),
            nullable=False,
            server_default="256",
        ),
    )
    op.add_column(
        "mcp_servers",
        sa.Column(
            "tool_definition_max_bytes",
            sa.Integer(),
            nullable=False,
            server_default="65536",
        ),
    )


def downgrade() -> None:
    op.drop_column("mcp_servers", "tool_definition_max_bytes")
    op.drop_column("mcp_servers", "tool_catalog_max_bytes")
    op.drop_column("mcp_servers", "tool_catalog_max_count")
