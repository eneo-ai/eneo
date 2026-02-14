"""add indexes for activity stats

Adds indexes to improve insights activity queries on:
- Users (tenant_id)
- Sessions (user_id, created_at)

Revision ID: add_activity_indexes
Revises: add_analytics_indexes
Create Date: 2026-01-31

"""

from alembic import op

# revision identifiers, used by Alembic
revision = "add_activity_indexes"
down_revision = "add_analytics_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_users_tenant_id",
        "users",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "idx_sessions_user_created_at",
        "sessions",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_sessions_user_created_at", table_name="sessions")
    op.drop_index("idx_users_tenant_id", table_name="users")
