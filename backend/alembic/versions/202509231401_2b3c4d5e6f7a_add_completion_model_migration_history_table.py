"""add completion model migration history table

Revision ID: add_migration_history
Revises: add_usage_stats
Create Date: 2025-09-23 14:01:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic
revision = "2b3c4d5e6f7a"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the completion_model_migration_history table
    op.create_table(
        "completion_model_migration_history",
        sa.Column(
            "id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("migration_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("from_model_id", UUID(as_uuid=True), nullable=False),
        sa.Column("to_model_id", UUID(as_uuid=True), nullable=False),
        sa.Column("initiated_by", UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("entity_types", sa.JSON, nullable=True),
        sa.Column("affected_count", sa.Integer(), nullable=False, default=0),
        sa.Column("migrated_count", sa.Integer(), nullable=False, default=0),
        sa.Column("failed_count", sa.Integer(), nullable=False, default=0),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("warnings", sa.JSON, nullable=True),
        sa.Column("migration_details", sa.JSON, nullable=True),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["from_model_id"], ["completion_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_model_id"], ["completion_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["initiated_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for performance
    op.create_index("idx_migration_history_tenant", "completion_model_migration_history", ["tenant_id"])
    op.create_index("idx_migration_history_from_model", "completion_model_migration_history", ["from_model_id"])
    op.create_index("idx_migration_history_to_model", "completion_model_migration_history", ["to_model_id"])
    op.create_index("idx_migration_history_status", "completion_model_migration_history", ["status"])
    op.create_index("idx_migration_history_created_at", "completion_model_migration_history", ["created_at"])
    op.create_index("idx_migration_history_migration_id", "completion_model_migration_history", ["migration_id"])


def downgrade() -> None:
    # Drop indexes first
    op.drop_index("idx_migration_history_migration_id", "completion_model_migration_history")
    op.drop_index("idx_migration_history_created_at", "completion_model_migration_history")
    op.drop_index("idx_migration_history_status", "completion_model_migration_history")
    op.drop_index("idx_migration_history_to_model", "completion_model_migration_history")
    op.drop_index("idx_migration_history_from_model", "completion_model_migration_history")
    op.drop_index("idx_migration_history_tenant", "completion_model_migration_history")
    
    # Drop the table
    op.drop_table("completion_model_migration_history")