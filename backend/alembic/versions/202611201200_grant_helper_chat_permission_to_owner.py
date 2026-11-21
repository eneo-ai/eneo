"""grant helper chat permission to the predefined Owner role

Revision ID: 202611201200
Revises: 202611182000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202611201200"
down_revision: str | None = "202611182000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE roles
        SET permissions = array_append(permissions, 'helper_chat')
        WHERE predefined_source IN ('Owner')
          AND NOT ('helper_chat' = ANY(permissions))
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE roles
        SET permissions = array_remove(permissions, 'helper_chat')
        WHERE 'helper_chat' = ANY(permissions)
    """)
