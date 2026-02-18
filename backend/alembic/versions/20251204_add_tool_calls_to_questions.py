"""Add tool_calls JSON column to questions table.

Revision ID: 20251204_tool_calls
Revises: 20251103_consolidated_mcp
Create Date: 2025-12-04

Stores MCP tool call metadata (server_name, tool_name, arguments) for each message.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "20251204_tool_calls"
down_revision = "20251103_consolidated_mcp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column("tool_calls", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("questions", "tool_calls")
