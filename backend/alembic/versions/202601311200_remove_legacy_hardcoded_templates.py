# flake8: noqa

"""Remove legacy hardcoded templates

Remove all templates that were seeded via migrations (without tenant_id).
These are replaced by the tenant-scoped template management system
(admin API with CRUD, soft-delete, rollback, etc.).

Revision ID: remove_legacy_templates
Revises: c3670d9f940c
Create Date: 2026-01-31 12:00:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic
revision = "remove_legacy_templates"
down_revision = "c3670d9f940c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Delete all legacy templates that have no tenant_id (seeded by migrations)
    op.execute("DELETE FROM app_templates WHERE tenant_id IS NULL;")
    op.execute("DELETE FROM assistant_templates WHERE tenant_id IS NULL;")


def downgrade() -> None:
    # No downgrade - legacy templates should not be restored.
    # Use the admin API to create templates instead.
    pass
