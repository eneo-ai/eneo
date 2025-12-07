"""add audit logs performance indexes

Revision ID: audit_performance_indexes
Revises: create_audit_logs
Create Date: 2025-11-09

This migration improves audit logs query performance by:
1. Adding stable pagination with secondary id sort
2. Adding partial indexes for active logs only
3. Adding trigram indexes for text search
4. Optimizing common filter combinations
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = "audit_performance_indexes"
down_revision = "create_audit_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pg_trgm extension for trigram text search
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")

    # Drop old indexes (they don't have stable secondary sort)
    op.drop_index("idx_audit_tenant_timestamp", "audit_logs")
    op.drop_index("idx_audit_actor", "audit_logs")
    op.drop_index("idx_audit_action", "audit_logs")
    op.drop_index("idx_audit_active", "audit_logs")
    # Keep idx_audit_entity as-is (entity lookups don't need timestamp sorting)

    # Create new indexes with stable pagination (id DESC as secondary sort)
    # This prevents row instability when timestamps are identical

    # 1. Primary pagination index - tenant + timestamp + id for stable sorting
    op.create_index(
        "idx_audit_tenant_timestamp_id",
        "audit_logs",
        ["tenant_id", sa.text("timestamp DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # 2. Action filter index - tenant + action + timestamp + id
    op.create_index(
        "idx_audit_tenant_action_timestamp_id",
        "audit_logs",
        ["tenant_id", "action", sa.text("timestamp DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # 3. Actor filter index - tenant + actor + timestamp + id
    op.create_index(
        "idx_audit_tenant_actor_timestamp_id",
        "audit_logs",
        ["tenant_id", "actor_id", sa.text("timestamp DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # 4. Trigram index for description text search
    # Using GIN + btree_gin to combine exact tenant match with fuzzy text search
    op.execute(
        """
        CREATE INDEX idx_audit_description_trgm
        ON audit_logs USING gin (tenant_id, lower(description) gin_trgm_ops)
        WHERE deleted_at IS NULL
        """
    )

    # 5. JSONB index for metadata queries (if needed for filtering by metadata fields)
    op.create_index(
        "idx_audit_metadata_gin",
        "audit_logs",
        ["metadata"],
        postgresql_using="gin",
        postgresql_ops={"metadata": "jsonb_path_ops"},
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    # Drop new indexes
    op.drop_index("idx_audit_metadata_gin", "audit_logs")
    op.execute("DROP INDEX IF EXISTS idx_audit_description_trgm")
    op.drop_index("idx_audit_tenant_actor_timestamp_id", "audit_logs")
    op.drop_index("idx_audit_tenant_action_timestamp_id", "audit_logs")
    op.drop_index("idx_audit_tenant_timestamp_id", "audit_logs")

    # Restore old indexes
    op.create_index("idx_audit_tenant_timestamp", "audit_logs", ["tenant_id", "timestamp"])
    op.create_index("idx_audit_actor", "audit_logs", ["tenant_id", "actor_id", "timestamp"])
    op.create_index("idx_audit_action", "audit_logs", ["tenant_id", "action", "timestamp"])
    op.create_index(
        "idx_audit_active",
        "audit_logs",
        ["tenant_id", "timestamp"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # Note: We don't drop pg_trgm extension in downgrade as other tables might use it
