"""add tool_based_knowledge column to assistants

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


def upgrade() -> None:
    op.add_column(
        "assistants",
        sa.Column("tool_based_knowledge", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("assistants", "tool_based_knowledge")
