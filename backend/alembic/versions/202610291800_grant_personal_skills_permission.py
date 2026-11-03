"""grant personal skills permission to the predefined Owner role

Revision ID: 202610291800
Revises: 202610261300
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202610291800"
down_revision: str | None = "202610261300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE roles
        SET permissions = array_append(permissions, 'personal_skills')
        WHERE predefined_source IN ('Owner')
          AND NOT ('personal_skills' = ANY(permissions))
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE roles
        SET permissions = array_remove(permissions, 'personal_skills')
        WHERE 'personal_skills' = ANY(permissions)
    """)
