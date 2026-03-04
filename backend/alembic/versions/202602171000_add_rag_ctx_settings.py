"""add_rag_ctx_settings

Revision ID: add_rag_ctx_settings
Revises: rename_integration_perm
Create Date: 2026-02-17 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = "add_rag_ctx_settings"
down_revision = "rename_integration_perm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add rag_context_type column - stores the type of context limit
    # Values: 'percentage', 'fixed_chunks', 'auto_relevance' (NULL = default 50% of context)
    op.add_column(
        "assistants",
        sa.Column("rag_context_type", sa.String, nullable=True)
    )
    # Add rag_context_value column - stores the value for percentage or fixed chunks
    op.add_column(
        "assistants",
        sa.Column("rag_context_value", sa.Integer, nullable=True)
    )


def downgrade() -> None:
    op.drop_column("assistants", "rag_context_value")
    op.drop_column("assistants", "rag_context_type")