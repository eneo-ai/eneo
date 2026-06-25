"""chat_session_mcp_state: persist MCP-protocol session id per (chat session, mcp server)

Eneo opens a fresh ``streamablehttp_client`` connection per user turn. The MCP
protocol's ``mcp-session-id`` (server-assigned on ``initialize``) lets MCP
servers scope state to a logical session instead of a single HTTP transport.
Persisting it keyed to (chat_session_id, mcp_server_id) lets the next turn
resume the same logical MCP session by sending the stored id as the initial
``Mcp-Session-Id`` header.

Generic shape: any MCP server that returns a session id on initialize can use
the same row.

Revision ID: 202605171000
Revises: b4f2a9c1e7d3
Create Date: 2026-05-17
"""

import sqlalchemy as sa

from alembic import op

revision = "202605171000"
down_revision = "b4f2a9c1e7d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_session_mcp_state",
        sa.Column("chat_session_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("mcp_server_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("mcp_session_id", sa.Text(), nullable=False),
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


def downgrade() -> None:
    op.drop_index(
        "ix_chat_session_mcp_state_mcp_server_id",
        table_name="chat_session_mcp_state",
    )
    op.drop_table("chat_session_mcp_state")
