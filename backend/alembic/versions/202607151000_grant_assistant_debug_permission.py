"""Grant assistant_debug permission to existing Owner and AI Configurator roles.

Revision ID: 202607151000
Revises: 202607101002
Create Date: 2026-07-15

Backfills the new ``Permission.ASSISTANT_DEBUG`` bit onto every tenant's Owner
and AI Configurator roles so existing tenants keep access to the chat debug
panel when the role gate replaces the deploy-level feature flag. The YAML
template at ``backend/src/eneo/server/dependencies/predefined_roles.yml``
already includes ``assistant_debug`` for new tenants — this migration covers
the existing ones.

Targets ``predefined_source IN ('Owner', 'AI Configurator')`` only. User and
custom roles are intentionally untouched: tenant admins explicitly grant
``assistant_debug`` to roles they want to delegate to.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "202607151000"
down_revision = "202607101002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_append(permissions, 'assistant_debug')
        WHERE predefined_source IN ('Owner', 'AI Configurator')
          AND NOT ('assistant_debug' = ANY(permissions));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE roles
        SET permissions = array_remove(permissions, 'assistant_debug')
        WHERE predefined_source IN ('Owner', 'AI Configurator');
        """
    )
