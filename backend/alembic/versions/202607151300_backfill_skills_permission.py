"""backfill Skill use and management permissions onto existing capable roles

Revision ID: 202607151300
Revises: 202607151200
Create Date: 2026-07-15 13:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607151300"
down_revision: str | None = "202607151200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_append(permissions, 'skills')
        WHERE (
            'assistants' = ANY(permissions)
            OR 'apps' = ANY(permissions)
            OR 'AI' = ANY(permissions)
            OR 'admin' = ANY(permissions)
        )
          AND NOT ('skills' = ANY(permissions))
        """
    )
    op.execute(
        """
        UPDATE roles
        SET permissions = array_append(permissions, 'skills_management')
        WHERE (
            'AI' = ANY(permissions)
            OR 'admin' = ANY(permissions)
        )
          AND NOT ('skills_management' = ANY(permissions))
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_remove(permissions, 'skills_management')
        WHERE 'skills_management' = ANY(permissions)
        """
    )
    op.execute(
        """
        UPDATE roles
        SET permissions = array_remove(permissions, 'skills')
        WHERE 'skills' = ANY(permissions)
        """
    )
