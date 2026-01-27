"""add_auth_type_to_user_integrations
Revision ID: ba3f702be082
Revises: 8caa65099dcf
Create Date: 2025-11-06 19:28:11.525275
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic
revision = 'ba3f702be082'
down_revision = '8caa65099dcf'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create auth_type enum
    auth_type_enum = postgresql.ENUM('user_oauth', 'tenant_app', name='auth_type', create_type=False)
    auth_type_enum.create(op.get_bind(), checkfirst=True)

    # Add auth_type column with default value 'user_oauth' for existing rows
    op.add_column(
        'user_integrations',
        sa.Column('auth_type', auth_type_enum, nullable=False, server_default='user_oauth')
    )

    # Add tenant_app_id column (nullable, FK to tenant_sharepoint_apps)
    op.add_column(
        'user_integrations',
        sa.Column('tenant_app_id', postgresql.UUID(as_uuid=True), nullable=True)
    )

    # Create FK constraint
    op.create_foreign_key(
        'fk_user_integrations_tenant_app',
        'user_integrations',
        'tenant_sharepoint_apps',
        ['tenant_app_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # Create index for performance
    op.create_index(
        op.f('ix_user_integrations_tenant_app_id'),
        'user_integrations',
        ['tenant_app_id'],
        unique=False
    )

def downgrade() -> None:
    op.drop_index(op.f('ix_user_integrations_tenant_app_id'), table_name='user_integrations')
    op.drop_constraint('fk_user_integrations_tenant_app', 'user_integrations', type_='foreignkey')
    op.drop_column('user_integrations', 'tenant_app_id')
    op.drop_column('user_integrations', 'auth_type')

    # Drop the enum type
    auth_type_enum = postgresql.ENUM('user_oauth', 'tenant_app', name='auth_type')
    auth_type_enum.drop(op.get_bind(), checkfirst=True)