# flake8: noqa

"""add sync_logs table for detailed sync history

Revision ID: 202510281430
Revises: 202510231400
Create Date: 2025-10-28 14:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic
revision = "202510281430"
down_revision = "202510231400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_logs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("integration_knowledge_id", sa.UUID(), nullable=False),
        sa.Column("sync_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sync_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["integration_knowledge_id"],
            ["integration_knowledge.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sync_logs_integration_knowledge_id",
        "sync_logs",
        ["integration_knowledge_id"],
    )
    op.create_index(
        "ix_sync_logs_created_at",
        "sync_logs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_sync_logs_created_at", table_name="sync_logs")
    op.drop_index("ix_sync_logs_integration_knowledge_id", table_name="sync_logs")
    op.drop_table("sync_logs")
