"""make_user_integrations_user_id_nullable

Make user_integrations.user_id nullable to support person-independent tenant_app integrations.
Tenant app integrations (using application permissions) should not be tied to any specific user,
so they can persist even when the admin who configured them leaves.

Revision ID: 7e4f8a9c5d12
Revises: ba3f702be082
Create Date: 2025-11-11 12:30:00.000000
"""

from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic
revision = '7e4f8a9c5d12'
down_revision = 'ba3f702be082'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the existing unique constraint (it includes user_id)
    op.drop_constraint(
        'user_integration_user_id_tenant_integration_id_unique',
        'user_integrations',
        type_='unique'
    )

    # Make user_id nullable
    # For tenant_app integrations, user_id will be NULL (person-independent)
    # For user_oauth integrations, user_id will still be required (person-specific)
    op.alter_column(
        'user_integrations',
        'user_id',
        existing_type=postgresql.UUID(),
        nullable=True
    )

    # Recreate the unique constraint
    # Note: PostgreSQL treats NULL as distinct in unique constraints,
    # so multiple rows with user_id=NULL are allowed (which is what we want for tenant apps)
    op.create_unique_constraint(
        'user_integration_user_id_tenant_integration_id_unique',
        'user_integrations',
        ['user_id', 'tenant_integration_id']
    )


def downgrade() -> None:
    # This downgrade is DESTRUCTIVE - it will fail if there are any rows with user_id=NULL
    # First drop the unique constraint
    op.drop_constraint(
        'user_integration_user_id_tenant_integration_id_unique',
        'user_integrations',
        type_='unique'
    )

    # Make user_id NOT NULL again
    # WARNING: This will fail if there are any tenant_app integrations with user_id=NULL
    op.alter_column(
        'user_integrations',
        'user_id',
        existing_type=postgresql.UUID(),
        nullable=False
    )

    # Recreate the unique constraint
    op.create_unique_constraint(
        'user_integration_user_id_tenant_integration_id_unique',
        'user_integrations',
        ['user_id', 'tenant_integration_id']
    )
