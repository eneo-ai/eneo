"""Grant api_keys permission to existing Owner roles.

Revision ID: 202604281200
Revises: 202604231400
Create Date: 2026-04-28

Backfills the new ``Permission.API_KEYS`` bit onto every tenant's Owner role
so existing tenants don't lose API-key creation when the new gate at
``POST /api-keys`` lands. The YAML template at
``backend/src/eneo/server/dependencies/predefined_roles.yml`` already
includes ``api_keys`` for new tenants — this migration covers the existing
ones.

Targets ``predefined_source = 'Owner'`` only. AI Configurator, User, and
custom roles are intentionally untouched: tenant admins explicitly grant
``api_keys`` to roles they want to delegate to.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "202604281200"
down_revision = "202604231400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_append(permissions, 'api_keys')
        WHERE predefined_source = 'Owner'
          AND NOT ('api_keys' = ANY(permissions));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_remove(permissions, 'api_keys')
        WHERE predefined_source = 'Owner';
        """
    )
