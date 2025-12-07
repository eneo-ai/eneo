"""Add performance indexes for data retention queries

Revision ID: retention_perf_indexes
Revises: audit_description_trgm
Create Date: 2025-12-05

These indexes optimize batch deletion queries used by the data retention service.
Without them, full table scans occur during retention cleanup.

Note: Audit logs index is intentionally omitted - audit logs are planned
to be streamed to a separate database for security and compliance.
The nightly cron job can tolerate slower deletion for audit logs.
"""

from alembic import op

# revision identifiers, used by Alembic
revision = 'retention_perf_indexes'
down_revision = 'audit_description_trgm'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Questions table indexes for retention queries
    # - created_at: Used in WHERE clause for date-based deletion
    # - assistant_id + created_at: Compound index for hierarchical retention lookup
    # - session_id: Used in orphaned session cleanup (NOT EXISTS check)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_questions_created_at
        ON questions (created_at)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_questions_assistant_created
        ON questions (assistant_id, created_at)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_questions_session_id
        ON questions (session_id)
    """)

    # App runs table index for retention queries
    # - created_at: Used in WHERE clause for date-based deletion
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_app_runs_created_at
        ON app_runs (created_at)
    """)

    # Sessions table index for orphaned session cleanup
    # - created_at: Used in WHERE clause for date-based deletion
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_created_at
        ON sessions (created_at)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sessions_created_at")
    op.execute("DROP INDEX IF EXISTS idx_app_runs_created_at")
    op.execute("DROP INDEX IF EXISTS idx_questions_session_id")
    op.execute("DROP INDEX IF EXISTS idx_questions_assistant_created")
    op.execute("DROP INDEX IF EXISTS idx_questions_created_at")
