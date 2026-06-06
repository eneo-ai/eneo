"""Add forward_identity column to mcp_servers.

Revision ID: 202606061000
Revises: 202606281200
Create Date: 2026-06-06
"""

import sqlalchemy as sa

from alembic import op

revision = "202606061000"
down_revision = "202606281200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column(
            "forward_identity",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("mcp_servers", "forward_identity")
