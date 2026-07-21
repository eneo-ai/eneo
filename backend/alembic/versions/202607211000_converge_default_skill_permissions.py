"""converge predefined Skill permissions to Owner only

Revision ID: 202607211000
Revises: 202607201830
Create Date: 2026-07-21 10:00:00.000000

The earlier Skills migration was exercised by development environments before
the predefined role policy was narrowed. This revision converges those roles
without changing tenant-defined custom roles.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607211000"
down_revision: str | None = "202607201830"
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
    op.execute(
        """
        UPDATE roles
        SET permissions = array_remove(
            array_remove(permissions, 'skills_management'),
            'skills'
        )
        WHERE predefined_source IN ('User', 'AI Configurator')
        """
    )


def downgrade() -> None:
    # Restore the historical predefined-role policy. This intentionally widens
    # User and AI Configurator defaults; it cannot reconstruct per-tenant grants
    # that the upgrade removed.
    op.execute(
        """
        UPDATE roles
        SET permissions = array_append(permissions, 'skills')
        WHERE predefined_source IN ('User', 'AI Configurator')
          AND NOT ('skills' = ANY(permissions))
        """
    )
    op.execute(
        """
        UPDATE roles
        SET permissions = array_append(permissions, 'skills_management')
        WHERE predefined_source = 'AI Configurator'
          AND NOT ('skills_management' = ANY(permissions))
        """
    )
