"""add_service_account_support

Add service account authentication support to tenant_sharepoint_apps table.
Service accounts use OAuth with delegated permissions (refresh token flow)
as an alternative to tenant app's application permissions.

auth_method: 'tenant_app' (default) or 'service_account'
service_account_refresh_token_encrypted: Encrypted refresh token for service account
service_account_email: Email of the service account for display purposes

Revision ID: 202512111200
Revises: 202512041200
Create Date: 2025-12-11 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision = '202512111200'
down_revision = '202512041200'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add auth_method column with default 'tenant_app' for backward compatibility
    op.add_column(
        'tenant_sharepoint_apps',
        sa.Column('auth_method', sa.String(50), nullable=False, server_default='tenant_app')
    )

    # Add service_account_refresh_token_encrypted for storing encrypted refresh token
    op.add_column(
        'tenant_sharepoint_apps',
        sa.Column('service_account_refresh_token_encrypted', sa.Text(), nullable=True)
    )

    # Add service_account_email for display purposes
    op.add_column(
        'tenant_sharepoint_apps',
        sa.Column('service_account_email', sa.String(255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('tenant_sharepoint_apps', 'service_account_email')
    op.drop_column('tenant_sharepoint_apps', 'service_account_refresh_token_encrypted')
    op.drop_column('tenant_sharepoint_apps', 'auth_method')
