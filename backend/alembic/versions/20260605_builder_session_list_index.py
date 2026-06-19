"""add recency index for AI Builder session lists

Flow AI Builder lists the current user's sessions by tenant and actor,
ordered by recency. A composite btree index lets PostgreSQL satisfy the
tenant/actor filter and backward recency scan without sorting the user's
entire session set.

Revision ID: 20260605_builder_session_idx
Revises: a20ccbf34fff
Create Date: 2026-06-05 15:30:00
"""

from alembic import op

revision = "20260605_builder_session_idx"
down_revision = "a20ccbf34fff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS
                ix_builder_sessions_tenant_actor_updated
            ON builder_sessions (
                tenant_id,
                actor_user_id,
                updated_at,
                created_at
            );
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            """
            DROP INDEX CONCURRENTLY IF EXISTS
                ix_builder_sessions_tenant_actor_updated;
            """
        )
