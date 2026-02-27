"""rename integration_knowledge_list permission to integrations

Revision ID: rename_integration_perm
Revises: add_integration_wrappers
Create Date: 2026-02-12 10:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "rename_integration_perm"
down_revision = "add_integration_wrappers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_replace(permissions, 'integration_knowledge_list', 'integrations')
        WHERE 'integration_knowledge_list' = ANY(permissions)
        """
    )
    op.execute(
        """
        UPDATE predefined_roles
        SET permissions = array_replace(permissions, 'integration_knowledge_list', 'integrations')
        WHERE 'integration_knowledge_list' = ANY(permissions)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_replace(permissions, 'integrations', 'integration_knowledge_list')
        WHERE 'integrations' = ANY(permissions)
        """
    )
    op.execute(
        """
        UPDATE predefined_roles
        SET permissions = array_replace(permissions, 'integrations', 'integration_knowledge_list')
        WHERE 'integrations' = ANY(permissions)
        """
    )
