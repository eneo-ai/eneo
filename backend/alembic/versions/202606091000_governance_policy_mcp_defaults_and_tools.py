"""governance policy: per-server chat default + disabled-tool deny-set

Adds `is_default_enabled` to governance_policy_mcp_servers (whether an
allowed server starts switched ON in the user's chat) and a
governance_policy_disabled_mcp_tools deny-set table (tools the admin
switched OFF on allowed servers — new tools synced onto a server are
allowed automatically).

Revision ID: 202606091000
Revises: 202605221100
Create Date: 2026-06-09
"""

import sqlalchemy as sa

from alembic import op

revision = "202606091000"
down_revision = "202605221100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "governance_policy_mcp_servers",
        sa.Column(
            "is_default_enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.create_table(
        "governance_policy_disabled_mcp_tools",
        sa.Column("policy_id", sa.UUID(), nullable=False),
        sa.Column("mcp_tool_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"], ["governance_policies.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["mcp_tool_id"], ["mcp_server_tools.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("policy_id", "mcp_tool_id"),
    )


def downgrade() -> None:
    op.drop_table("governance_policy_disabled_mcp_tools")
    op.drop_column("governance_policy_mcp_servers", "is_default_enabled")
