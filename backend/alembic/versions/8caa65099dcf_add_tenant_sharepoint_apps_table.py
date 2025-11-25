"""add_tenant_sharepoint_apps_table
Revision ID: 8caa65099dcf
Revises: 202511061533
Create Date: 2025-11-06 19:27:40.038232
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic
revision = '8caa65099dcf'
down_revision = '202511061533'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create tenant_sharepoint_apps table
    op.create_table(
        'tenant_sharepoint_apps',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('client_id', sa.String(length=255), nullable=False),
        sa.Column('client_secret_encrypted', sa.Text(), nullable=False),
        sa.Column('certificate_path', sa.Text(), nullable=True),
        sa.Column('tenant_domain', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', name='uq_tenant_sharepoint_app_tenant_id')
    )
    op.create_index(op.f('ix_tenant_sharepoint_apps_tenant_id'), 'tenant_sharepoint_apps', ['tenant_id'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_tenant_sharepoint_apps_tenant_id'), table_name='tenant_sharepoint_apps')
    op.drop_table('tenant_sharepoint_apps')