"""Add pg_trgm index on audit_logs description for entity search

Revision ID: audit_description_trgm
Revises: d5a731604652
Create Date: 2025-12-05

Note: CREATE EXTENSION requires superuser privileges. If running in a
restricted environment, ensure pg_trgm is pre-installed before migration.
"""

from alembic import op

# revision identifiers, used by Alembic
revision = 'audit_description_trgm'
down_revision = 'd5a731604652'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pg_trgm extension (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Create GIN index for trigram matching (idempotent)
    # Note: CONCURRENTLY requires running outside a transaction
    # For regular migration, use non-concurrent index creation
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_description_trgm
        ON audit_logs USING GIN (description gin_trgm_ops)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_audit_description_trgm")
