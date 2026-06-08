"""Add edit-mode flag + materialized edit assistant reference to tenants.

Edit mode (configure an assistant by chatting) is driven by a persisted, tenant-level
"Configuration Assistant" that holds the config persona (its prompt), the helper model
(its completion_model) and any extra MCP tools (its mcp_servers). This adds:

- ``edit_mode_enabled``: admin toggle; when on, the tenant has a provisioned edit assistant.
- ``edit_assistant_id``: FK to that assistant. ON DELETE SET NULL so deleting the assistant
  clears the reference (edit mode then falls back to the built-in default persona).

Revision ID: 202606081100
Revises: 202605251000
Create Date: 2026-06-08
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "202606081100"
down_revision = "202605251000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "edit_mode_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "tenants",
        sa.Column("edit_assistant_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tenants_edit_assistant",
        "tenants",
        "assistants",
        ["edit_assistant_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_tenants_edit_assistant", "tenants", type_="foreignkey")
    op.drop_column("tenants", "edit_assistant_id")
    op.drop_column("tenants", "edit_mode_enabled")
