"""Add supports_tool_calling to completion_models

Adds a separate boolean flag for tool/function calling support,
decoupled from the vision flag which was previously used as a proxy.

Revision ID: 20260129_supports_tool_calling
Revises: 20251204_tool_calls
Create Date: 2026-01-29
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = "20260129_supports_tool_calling"
down_revision = "20251204_tool_calls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "completion_models",
        sa.Column(
            "supports_tool_calling",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    # Backfill: copy vision value to supports_tool_calling as a safe default,
    # since vision models were previously the ones with tool calling enabled
    op.execute(
        "UPDATE completion_models SET supports_tool_calling = vision"
    )


def downgrade() -> None:
    op.drop_column("completion_models", "supports_tool_calling")
