"""Grant capability permissions to existing roles

Web search and image generation become role permissions (``web_search`` and
``image_generation``). Both capabilities were available to every user of a
tenant before, so every existing role (predefined and custom) receives them;
tenant admins narrow access by removing the permission from a role. The YAML
template in ``server/dependencies/predefined_roles.yml`` covers new tenants.

Revision ID: 202607101006
Revises: 202607101005
Create Date: 2026-09-03

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "202607101006"
down_revision = "202607101005"
branch_labels = None
depends_on = None

_PERMISSIONS = ("web_search", "image_generation")


def upgrade() -> None:
    for permission in _PERMISSIONS:
        op.execute(
            f"""
            UPDATE roles
            SET permissions = array_append(permissions, '{permission}')
            WHERE NOT ('{permission}' = ANY(permissions));
            """
        )


def downgrade() -> None:
    for permission in _PERMISSIONS:
        op.execute(
            f"""
            UPDATE roles
            SET permissions = array_remove(permissions, '{permission}');
            """
        )
