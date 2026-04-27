"""drop obsolete flow_step_mcp_tools table

Revision ID: 20260426_drop_step_mcp_tools
Revises: 20260426_latest_plan_fk
Create Date: 2026-04-26 00:00:00.000000

Flow step MCP access is now stored on each step's flow-managed assistant
through `assistant_mcp_servers` and `assistant_mcp_server_tools`. Keeping
the old writable join table would create two apparent sources of truth
before the feature reaches production.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260426_drop_step_mcp_tools"
down_revision = "20260426_latest_plan_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("flow_step_mcp_tools")


def downgrade() -> None:
    op.create_table(
        "flow_step_mcp_tools",
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "flow_step_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flow_steps.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "mcp_server_tool_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_server_tools.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["flow_step_id", "tenant_id"],
            ["flow_steps.id", "flow_steps.tenant_id"],
            name="fk_flow_step_mcp_tools_step_tenant",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_flow_step_mcp_tools_tenant_id",
        "flow_step_mcp_tools",
        ["tenant_id"],
        unique=False,
    )
