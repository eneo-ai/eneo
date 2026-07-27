"""Version persisted MCP sessions when identity-forwarding policy changes.

Revision ID: 202607221000
Revises: 202607211200
Create Date: 2026-07-22
"""

import sqlalchemy as sa

from alembic import op

revision = "202607221000"
down_revision = "202607211200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column(
            "identity_policy_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "chat_session_mcp_state",
        sa.Column(
            "identity_policy_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_session_mcp_state", "identity_policy_generation")
    op.drop_column("mcp_servers", "identity_policy_generation")
