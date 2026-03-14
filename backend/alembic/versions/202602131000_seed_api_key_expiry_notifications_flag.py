"""Seed api_key_expiry_notifications feature flag

Revision ID: 202602131000
Revises: 33166e5884df
Create Date: 2026-02-13
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "202602131000"
down_revision = "33166e5884df"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Defaults ON so existing tenants keep receiving expiry notices after rollout.
    op.execute("""
        INSERT INTO global_feature_flags (id, name, description, enabled, created_at, updated_at)
        VALUES (
            gen_random_uuid(),
            'api_key_expiry_notifications',
            'Enable API key expiry notification features for tenant users',
            true,
            now(),
            now()
        )
        ON CONFLICT (name) DO NOTHING
    """)

    op.execute("""
        INSERT INTO tenant_feature_flags (name, feature_id, tenant_id, enabled, created_at, updated_at)
        SELECT
            'api_key_expiry_notifications',
            f.id,
            t.id,
            true,
            now(),
            now()
        FROM tenants t
        CROSS JOIN global_feature_flags f
        WHERE f.name = 'api_key_expiry_notifications'
        ON CONFLICT (feature_id, tenant_id) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM tenant_feature_flags WHERE name = 'api_key_expiry_notifications'
    """)
    op.execute("""
        DELETE FROM global_feature_flags WHERE name = 'api_key_expiry_notifications'
    """)
