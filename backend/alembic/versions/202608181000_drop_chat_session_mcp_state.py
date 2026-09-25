"""Drop MCP protocol-session persistence (unreleased feature removed)

MCP spec revision 2026-07-28 removes protocol-level sessions from the
Streamable HTTP transport; servers that need cross-call state use explicit
handles passed as ordinary tool arguments instead. Eneo therefore no longer
persists or resumes ``Mcp-Session-Id`` values, so the per-(chat session,
mcp server) state table and the ``identity_policy_generation`` counter that
versioned persisted sessions both go away.

Revision ID: 202608181000
Revises: 202608121500
Create Date: 2026-08-18
"""

import sqlalchemy as sa

from alembic import op

revision = "202608181000"
down_revision = "202608121500"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        "ix_chat_session_mcp_state_mcp_server_id",
        table_name="chat_session_mcp_state",
    )
    op.drop_table("chat_session_mcp_state")
    op.drop_column("mcp_servers", "identity_policy_generation")


def downgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column(
            "identity_policy_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_table(
        "chat_session_mcp_state",
        sa.Column("chat_session_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("mcp_server_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("mcp_session_id", sa.Text(), nullable=False),
        sa.Column(
            "identity_policy_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
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
        sa.PrimaryKeyConstraint(
            "chat_session_id", "mcp_server_id", name="pk_chat_session_mcp_state"
        ),
        sa.ForeignKeyConstraint(
            ["chat_session_id"], ["sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["mcp_server_id"], ["mcp_servers.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_chat_session_mcp_state_mcp_server_id",
        "chat_session_mcp_state",
        ["mcp_server_id"],
    )
