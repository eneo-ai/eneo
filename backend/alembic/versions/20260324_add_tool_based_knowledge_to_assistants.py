"""add knowledge_mode to assistants and pinned flag to collection junction table

Revision ID: 20260324_tool_knowledge
Revises: 20260324_collection_desc
Create Date: 2026-03-24
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260324_tool_knowledge"
down_revision = "20260324_collection_desc"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :table AND column_name = :column"
    ), {"table": table, "column": column})
    return result.fetchone() is not None


def upgrade() -> None:
    # Clean up old POC column if it exists
    if _column_exists("assistants", "tool_based_knowledge"):
        op.drop_column("assistants", "tool_based_knowledge")

    if not _column_exists("assistants", "knowledge_mode"):
        op.add_column(
            "assistants",
            sa.Column("knowledge_mode", sa.String(), server_default="tool", nullable=False),
        )

    if not _column_exists("assistants_groups", "pinned"):
        op.add_column(
            "assistants_groups",
            sa.Column("pinned", sa.Boolean(), server_default="false", nullable=False),
        )


def downgrade() -> None:
    if _column_exists("assistants_groups", "pinned"):
        op.drop_column("assistants_groups", "pinned")
    if _column_exists("assistants", "knowledge_mode"):
        op.drop_column("assistants", "knowledge_mode")
