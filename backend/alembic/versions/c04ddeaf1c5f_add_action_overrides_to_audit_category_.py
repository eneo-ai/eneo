"""add_action_overrides_to_audit_category_config

Revision ID: c04ddeaf1c5f
Revises: c8661891e8cd
Create Date: 2025-11-17 21:30:00.000000

Adds granular per-action configuration to existing audit_category_config table:
- action_overrides JSONB column for disabling specific actions within a category
- audit_logging_enabled feature flag for global on/off control
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic
revision = 'c04ddeaf1c5f'
down_revision = 'c8661891e8cd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ============================================================================
    # EXTEND EXISTING TABLE
    # ============================================================================

    # Add action_overrides JSONB column to existing audit_category_config table
    # Stores per-action overrides: {"user_created": false, "api_key_generated": false}
    # If action not in overrides, defaults to category.enabled value
    op.add_column(
        'audit_category_config',
        sa.Column(
            'action_overrides',
            JSONB,
            nullable=False,
            server_default='{}',
            comment='Per-action overrides: {"action_name": true/false}. Empty = use category setting.'
        )
    )

    # ============================================================================
    # FEATURE FLAG FOR GLOBAL TOGGLE
    # ============================================================================

    # Create audit_logging_enabled feature flag (default true = enabled)
    # Use ON CONFLICT in case it already exists
    op.execute("""
        INSERT INTO global_feature_flags (id, name, description, enabled, created_at, updated_at)
        VALUES (
            gen_random_uuid(),
            'audit_logging_enabled',
            'Master toggle for all audit logging functionality',
            true,
            now(),
            now()
        )
        ON CONFLICT (name) DO NOTHING
    """)

    # Enable for all existing tenants by default (backward compatible)
    # Use ON CONFLICT in case tenant already has the flag
    op.execute("""
        INSERT INTO tenant_feature_flags (name, feature_id, tenant_id, enabled, created_at, updated_at)
        SELECT
            'audit_logging_enabled',
            f.id,
            t.id,
            true,
            now(),
            now()
        FROM tenants t
        CROSS JOIN global_feature_flags f
        WHERE f.name = 'audit_logging_enabled'
        ON CONFLICT (feature_id, tenant_id) DO NOTHING
    """)


def downgrade() -> None:
    # Remove feature flag
    op.execute("""
        DELETE FROM tenant_feature_flags WHERE name = 'audit_logging_enabled'
    """)
    op.execute("""
        DELETE FROM global_feature_flags WHERE name = 'audit_logging_enabled'
    """)

    # Remove column
    op.drop_column('audit_category_config', 'action_overrides')
