"""add admin insights history indexes

Revision ID: 9d2a6c01f3e7
Revises: add_activity_indexes
Create Date: 2026-02-11
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "9d2a6c01f3e7"
down_revision = "add_activity_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Stable cursor pagination and date-range traversal for admin insights history.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sessions_assistant_created_id
        ON sessions (assistant_id, created_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_questions_session_created_id
        ON questions (session_id, created_at DESC, id DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_questions_session_created_id")
    op.execute("DROP INDEX IF EXISTS idx_sessions_assistant_created_id")
