"""enable_integrations_for_existing_tenants

This migration enables all available integrations for all existing tenants.
This is a one-time migration to populate the tenant_integrations table with all
integration combinations, allowing admins to selectively enable/disable them per tenant.
New tenants created after this migration will NOT have integrations auto-enabled;
admins must explicitly enable integrations via the admin panel.

Revision ID: 31f7ff287455
Revises: 202510301145
Create Date: 2025-10-30 13:35:13.027642
"""

from alembic import op


# revision identifiers, used by Alembic
revision = '31f7ff287455'
down_revision = '202510301145'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Enable all integrations for all tenants
    # This creates tenant_integration records for every combination of tenant and integration
    # that doesn't already exist
    op.execute("""
        INSERT INTO tenant_integrations (tenant_id, integration_id)
        SELECT t.id, i.id
        FROM tenants t
        CROSS JOIN integrations i
        WHERE NOT EXISTS (
            SELECT 1 FROM tenant_integrations ti
            WHERE ti.tenant_id = t.id AND ti.integration_id = i.id
        )
    """)

def downgrade() -> None:
    # We don't want to remove tenant_integrations in downgrade
    # as this could break user workflows. If you need to remove them,
    # do it manually via the UI or a separate script.
    pass