"""add_audit_category_config

Revision ID: c8661891e8cd
Revises: ba700144afe5
Create Date: 2025-11-17 17:40:52.294732

Adds audit_category_config table for granular control of audit logging categories.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic
revision = 'c8661891e8cd'
down_revision = 'ba700144afe5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create audit_category_config table
    op.create_table(
        'audit_category_config',
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='TRUE'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('tenant_id', 'category'),
        sa.CheckConstraint(
            "category IN ('admin_actions', 'user_actions', 'security_events', "
            "'file_operations', 'integration_events', 'system_actions', 'audit_access')",
            name='ck_audit_category_config_category_valid'
        )
    )

    # Create index for fast lookups
    op.create_index(
        'idx_audit_category_config_lookup',
        'audit_category_config',
        ['tenant_id', 'category'],
        unique=False
    )

    # Seed existing tenants with all categories enabled (default behavior)
    op.execute("""
        INSERT INTO audit_category_config (id, tenant_id, category, enabled, created_at, updated_at, created, updated)
        SELECT
            gen_random_uuid(),
            t.id,
            c.category,
            TRUE,
            NOW(),
            NOW(),
            NOW(),
            NOW()
        FROM tenants t
        CROSS JOIN (
            VALUES
                ('admin_actions'),
                ('user_actions'),
                ('security_events'),
                ('file_operations'),
                ('integration_events'),
                ('system_actions'),
                ('audit_access')
        ) AS c(category)
        WHERE NOT EXISTS (
            SELECT 1 FROM audit_category_config WHERE tenant_id = t.id
        );
    """)


def downgrade() -> None:
    # Drop index
    op.drop_index('idx_audit_category_config_lookup', table_name='audit_category_config')

    # Drop table
    op.drop_table('audit_category_config')