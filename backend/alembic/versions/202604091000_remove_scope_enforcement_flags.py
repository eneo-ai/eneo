"""Remove api_key_scope_enforcement and api_key_strict_mode feature flags

Scope enforcement and strict mode are now always active.

Revision ID: 202604091000
Revises: svc_api_keys_001
Create Date: 2026-04-09
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "202604091000"
down_revision = "svc_api_keys_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM tenant_feature_flags
        WHERE name IN ('api_key_scope_enforcement', 'api_key_strict_mode')
    """)
    op.execute("""
        DELETE FROM global_feature_flags
        WHERE name IN ('api_key_scope_enforcement', 'api_key_strict_mode')
    """)


def downgrade() -> None:
    # Re-insert scope enforcement flag (enabled by default)
    op.execute("""
        INSERT INTO global_feature_flags (id, name, description, enabled, created_at, updated_at)
        VALUES (
            gen_random_uuid(),
            'api_key_scope_enforcement',
            'Enforce API key scope boundaries per-tenant',
            true,
            now(),
            now()
        )
        ON CONFLICT (name) DO NOTHING
    """)
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

    # Re-insert strict mode flag (disabled by default)
    op.execute("""
        INSERT INTO global_feature_flags (id, name, description, enabled, created_at, updated_at)
        VALUES (
            gen_random_uuid(),
            'api_key_strict_mode',
            'Enforce strict API key behavior with fail-closed scope handling',
            false,
            now(),
            now()
        )
        ON CONFLICT (name) DO NOTHING
    """)
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
