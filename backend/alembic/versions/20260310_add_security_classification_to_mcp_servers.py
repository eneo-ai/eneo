"""add security classification to mcp servers and tool approval fields

Revision ID: mcp_security_classification
Revises: 9d2a6c01f3e7
Create Date: 2026-03-10
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "mcp_security_classification"
down_revision = "9d2a6c01f3e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add security_classification_id to mcp_servers (same pattern as completion_models)
    op.add_column(
        "mcp_servers",
        sa.Column(
            "security_classification_id",
            sa.Uuid(),
            sa.ForeignKey("security_classifications.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Add pending change tracking fields to mcp_server_tools for tool sync approval
    op.add_column(
        "mcp_server_tools",
        sa.Column("pending_description", sa.Text(), nullable=True),
    )
    op.add_column(
        "mcp_server_tools",
        sa.Column(
            "pending_input_schema",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
        ),
    )
    op.add_column(
        "mcp_server_tools",
        sa.Column(
            "requires_approval",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.add_column(
        "mcp_server_tools",
        sa.Column(
            "removed_from_remote",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("mcp_server_tools", "removed_from_remote")
    op.drop_column("mcp_server_tools", "requires_approval")
    op.drop_column("mcp_server_tools", "pending_input_schema")
    op.drop_column("mcp_server_tools", "pending_description")
    op.drop_column("mcp_servers", "security_classification_id")
