"""Seed api_key_strict_mode feature flag

Revision ID: 202602091000
Revises: 202602071100
Create Date: 2026-02-09
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "202602091000"
down_revision = "202602071100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Strict mode defaults OFF for staged rollout.
    op.execute("""
        INSERT INTO global_feature_flags (id, name, description, enabled, created_at, updated_at)
        VALUES (
            gen_random_uuid(),
            'api_key_strict_mode',
            'Enforce strict API key behavior with fail-closed scope handling and deterministic scoped access',
            false,
            now(),
            now()
        )
        ON CONFLICT (name) DO NOTHING
    """)

    # Seed tenant rows as disabled by default.
    op.execute("""
        INSERT INTO tenant_feature_flags (name, feature_id, tenant_id, enabled, created_at, updated_at)
        SELECT
            'api_key_strict_mode',
            f.id,
            t.id,
            false,
            now(),
            now()
        FROM tenants t
        CROSS JOIN global_feature_flags f
        WHERE f.name = 'api_key_strict_mode'
        ON CONFLICT (feature_id, tenant_id) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM tenant_feature_flags WHERE name = 'api_key_strict_mode'
    """)
    op.execute("""
        DELETE FROM global_feature_flags WHERE name = 'api_key_strict_mode'
    """)
