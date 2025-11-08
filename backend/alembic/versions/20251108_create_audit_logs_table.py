"""create audit logs table

Revision ID: create_audit_logs
Revises: c4af97fb702d
Create Date: 2025-11-08

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET

# revision identifiers, used by Alembic
revision = "create_audit_logs"
down_revision = "44bef4e52527"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the audit_logs table
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            UUID(as_uuid=True),
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
        # Multi-tenant isolation
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        # Actor information
        sa.Column("actor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("actor_type", sa.String(50), nullable=False, server_default="user"),
        # Action information
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        # Temporal information
        sa.Column(
            "timestamp",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Request context
        sa.Column("ip_address", INET, nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("request_id", UUID(as_uuid=True), nullable=True),
        # Business context
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        # Outcome
        sa.Column("outcome", sa.String(20), nullable=False, server_default="success"),
        sa.Column("error_message", sa.Text(), nullable=True),
        # Soft delete
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        # Foreign keys
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for query performance
    op.create_index("idx_audit_tenant_timestamp", "audit_logs", ["tenant_id", "timestamp"])
    op.create_index("idx_audit_actor", "audit_logs", ["tenant_id", "actor_id", "timestamp"])
    op.create_index("idx_audit_entity", "audit_logs", ["tenant_id", "entity_type", "entity_id"])
    op.create_index("idx_audit_action", "audit_logs", ["tenant_id", "action", "timestamp"])

    # Partial index for active logs
    op.create_index(
        "idx_audit_active",
        "audit_logs",
        ["tenant_id", "timestamp"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # Create audit_retention_policies table
    op.create_table(
        "audit_retention_policies",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("last_purge_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("purge_count", sa.Integer(), nullable=False, server_default="0"),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id"),
    )

    # Insert default retention policies for existing tenants
    op.execute(
        """
        INSERT INTO audit_retention_policies (tenant_id, retention_days)
        SELECT id, 365 FROM tenants
        ON CONFLICT (tenant_id) DO NOTHING
        """
    )


def downgrade() -> None:
    # Drop audit_retention_policies table
    op.drop_table("audit_retention_policies")

    # Drop indexes
    op.drop_index("idx_audit_active", "audit_logs")
    op.drop_index("idx_audit_action", "audit_logs")
    op.drop_index("idx_audit_entity", "audit_logs")
    op.drop_index("idx_audit_actor", "audit_logs")
    op.drop_index("idx_audit_tenant_timestamp", "audit_logs")

    # Drop the table
    op.drop_table("audit_logs")
