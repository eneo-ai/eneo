"""grant Skill use and management permissions to existing Owner roles

Revision ID: 202607221300
Revises: 202607221200
Create Date: 2026-07-22 13:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607221300"
down_revision: str | None = "202607221200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_append(permissions, 'skills')
        WHERE predefined_source = 'Owner'
          AND NOT ('skills' = ANY(permissions))
        """
    )
    op.execute(
        """
        UPDATE roles
        SET permissions = array_append(permissions, 'skills_management')
        WHERE predefined_source = 'Owner'
          AND NOT ('skills_management' = ANY(permissions))
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_remove(permissions, 'skills_management')
        WHERE predefined_source IN ('Owner', 'User', 'AI Configurator')
          AND 'skills_management' = ANY(permissions)
        """
    )
    op.execute(
        """
        UPDATE roles
        SET permissions = array_remove(permissions, 'skills')
        WHERE predefined_source IN ('Owner', 'User', 'AI Configurator')
          AND 'skills' = ANY(permissions)
        """
    )
