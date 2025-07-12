"""add completion model usage stats table

Revision ID: add_usage_stats
Revises: 1e58cb567f44
Create Date: 2025-07-08 09:27:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic
revision = "add_usage_stats"
down_revision = "1e58cb567f44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the completion_model_usage_stats table
    op.create_table(
        "completion_model_usage_stats",
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
        sa.Column("model_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("assistants_count", sa.Integer(), default=0, nullable=False),
        sa.Column("apps_count", sa.Integer(), default=0, nullable=False),
        sa.Column("services_count", sa.Integer(), default=0, nullable=False),
        sa.Column("questions_count", sa.Integer(), default=0, nullable=False),
        sa.Column("assistant_templates_count", sa.Integer(), default=0, nullable=False),
        sa.Column("app_templates_count", sa.Integer(), default=0, nullable=False),
        sa.Column("spaces_count", sa.Integer(), default=0, nullable=False),
        sa.Column("total_usage", sa.Integer(), default=0, nullable=False),
        sa.Column(
            "last_updated",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["model_id"], ["completion_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_id", "tenant_id", name="uq_model_tenant_stats"),
    )

    # Create indexes for performance
    op.create_index("idx_usage_stats_model_tenant", "completion_model_usage_stats", ["model_id", "tenant_id"])
    op.create_index("idx_usage_stats_updated", "completion_model_usage_stats", ["last_updated"])
    op.create_index("idx_usage_stats_total_usage", "completion_model_usage_stats", ["total_usage"])


def downgrade() -> None:
    # Drop indexes first
    op.drop_index("idx_usage_stats_total_usage", "completion_model_usage_stats")
    op.drop_index("idx_usage_stats_updated", "completion_model_usage_stats")
    op.drop_index("idx_usage_stats_model_tenant", "completion_model_usage_stats")
    
    # Drop the table
    op.drop_table("completion_model_usage_stats")