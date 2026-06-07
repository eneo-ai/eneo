"""Add external collection reference columns to mcp_servers.

Links a knowledge-source MCP server back to the external knowledge provider's
collection so later ingest can target it. Nullable: set only for servers
provisioned as a knowledge source.

Revision ID: 202606071000
Revises: 202606061002
Create Date: 2026-06-07
"""

import sqlalchemy as sa

from alembic import op

revision = "202606071000"
down_revision = "202606061002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column("external_collection_slug", sa.String(), nullable=True),
    )
    op.add_column(
        "mcp_servers",
        sa.Column("external_collection_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_servers", "external_collection_id")
    op.drop_column("mcp_servers", "external_collection_slug")
