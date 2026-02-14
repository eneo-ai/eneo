"""add indexes for analytics queries

Adds composite indexes to optimize date-range analytics queries on:
- Questions (tenant_id, created_at)
- AppRuns (tenant_id, created_at)
- Sessions (assistant_id, created_at)
- Sessions (group_chat_id, created_at)

Revision ID: add_analytics_indexes
Revises: c3670d9f940c
Create Date: 2026-01-30

"""

from alembic import op

# revision identifiers, used by Alembic
revision = "add_analytics_indexes"
down_revision = "c3670d9f940c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Composite index for token usage analytics on questions table
    # Queries filter by tenant_id and created_at date range
    op.create_index(
        "idx_questions_tenant_created_at",
        "questions",
        ["tenant_id", "created_at"],
        unique=False,
    )

    # Composite index for token usage analytics on app_runs table
    # Queries filter by tenant_id and created_at date range
    op.create_index(
        "idx_app_runs_tenant_created_at",
        "app_runs",
        ["tenant_id", "created_at"],
        unique=False,
    )

    # Composite index for session analytics by assistant
    # Queries filter by assistant_id and created_at date range
    op.create_index(
        "idx_sessions_assistant_created_at",
        "sessions",
        ["assistant_id", "created_at"],
        unique=False,
    )

    # Composite index for session analytics by group_chat
    # Queries filter by group_chat_id and created_at date range
    op.create_index(
        "idx_sessions_group_chat_created_at",
        "sessions",
        ["group_chat_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_sessions_group_chat_created_at", table_name="sessions")
    op.drop_index("idx_sessions_assistant_created_at", table_name="sessions")
    op.drop_index("idx_app_runs_tenant_created_at", table_name="app_runs")
    op.drop_index("idx_questions_tenant_created_at", table_name="questions")
