"""Seed api_key_scope_enforcement feature flag

Revision ID: 202602071100
Revises: 202602071000
Create Date: 2026-02-07
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "202602071100"
down_revision = "202602071000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the global feature flag (fail-closed: enabled by default)
    op.execute("""
        INSERT INTO global_feature_flags (id, name, description, enabled, created_at, updated_at)
        VALUES (
            gen_random_uuid(),
            'api_key_scope_enforcement',
            'Enforce API key scope restrictions (space/assistant/app-scoped keys are limited to their scope)',
            true,
            now(),
            now()
        )
        ON CONFLICT (name) DO NOTHING
    """)

    # Enable for all existing tenants by default
    op.execute("""
        INSERT INTO tenant_feature_flags (name, feature_id, tenant_id, enabled, created_at, updated_at)
        SELECT
            'api_key_scope_enforcement',
            f.id,
            t.id,
            true,
            now(),
            now()
        FROM tenants t
        CROSS JOIN global_feature_flags f
        WHERE f.name = 'api_key_scope_enforcement'
        ON CONFLICT (feature_id, tenant_id) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM tenant_feature_flags WHERE name = 'api_key_scope_enforcement'
    """)
    op.execute("""
        DELETE FROM global_feature_flags WHERE name = 'api_key_scope_enforcement'
    """)
