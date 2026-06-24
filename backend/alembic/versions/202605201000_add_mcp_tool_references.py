"""mcp_tool_references: per-question MCP resource citations

Captures MCP resource content blocks returned by tool calls so the chat UI
can render source chips for MCP-backed search. Generic across MCP servers:
only protocol-level resource fields are stored. Tenancy cascades via question_id.

GDPR / right-to-be-forgotten: rows include the resource snippet (`content`
column), which is partial copy of upstream document text. Deletion cascades
follow the same convention as `info_blob_references` and
`web_search_results`: ON DELETE CASCADE on `question_id` removes refs when
the parent Question is deleted, and Sessions cascade-delete their Questions.
Any future bulk-deletion endpoint that bypasses Question deletion (none today)
MUST also clear rows from this table.

Revision ID: 202605201000
Revises: 202605171000
Create Date: 2026-05-20
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202605201000"
down_revision = "202605171000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_tool_references",
        sa.Column("tool_call_id", sa.String(), nullable=True),
        sa.Column("mcp_tool_name", sa.String(), nullable=True),
        sa.Column("uri", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("content", sa.String(), nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "order", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("question_id", sa.UUID(), nullable=False),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
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
        sa.ForeignKeyConstraint(
            ["question_id"], ["questions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mcp_tool_references_question_id",
        "mcp_tool_references",
        ["question_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mcp_tool_references_question_id", table_name="mcp_tool_references"
    )
    op.drop_table("mcp_tool_references")
