"""Migrate legacy web_search_results into mcp_tool_references, drop table

Web search now flows through an external MCP provider, so citations land in
mcp_tool_references like every other tool result. Historical Tavily rows are
migrated with their original UUIDs preserved so existing <inref id="...">
prefixes in stored answers keep resolving. Title and score move into meta,
alongside sourceType="web-search" for frontend rendering.

Revision ID: 202607101001
Revises: 202607101000
Create Date: 2026-07-10

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "202607101001"
down_revision = "202607101000"
branch_labels = None
depends_on = None

LEGACY_TOOL_NAME = "legacy_web_search"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO mcp_tool_references
                (id, created_at, updated_at, question_id, uri, content,
                 mcp_tool_name, meta, "order")
            SELECT
                id, created_at, updated_at, question_id, url, content,
                :tool_name,
                jsonb_build_object(
                    'title', title,
                    'score', score,
                    'sourceType', 'web-search'
                ),
                0
            FROM web_search_results
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(tool_name=LEGACY_TOOL_NAME)
    )
    op.drop_table("web_search_results")


def downgrade() -> None:
    op.create_table(
        "web_search_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("question_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO web_search_results
                (id, created_at, updated_at, question_id, url, content,
                 title, score)
            SELECT
                id, created_at, updated_at, question_id, uri,
                COALESCE(content, ''),
                COALESCE(meta->>'title', ''),
                COALESCE((meta->>'score')::float, 0)
            FROM mcp_tool_references
            WHERE mcp_tool_name = :tool_name
            """
        ).bindparams(tool_name=LEGACY_TOOL_NAME)
    )
    op.execute(
        sa.text(
            "DELETE FROM mcp_tool_references WHERE mcp_tool_name = :tool_name"
        ).bindparams(tool_name=LEGACY_TOOL_NAME)
    )
