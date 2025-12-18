"""sharepoint site level subscriptions

Revision ID: 202511061533
Revises: 202411041401
Create Date: 2025-11-06 15:33:00.000000

Creates sharepoint_subscriptions table for site-level webhook management
and adds FK from integration_knowledge to sharepoint_subscriptions.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '202511061533'
down_revision: Union[str, None] = '202411041401'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create sharepoint_subscriptions table
    op.create_table(
        'sharepoint_subscriptions',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('user_integration_id', sa.UUID(), nullable=False),
        sa.Column('site_id', sa.Text(), nullable=False),
        sa.Column('subscription_id', sa.Text(), nullable=False),
        sa.Column('drive_id', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_integration_id'], ['user_integrations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_integration_id', 'site_id', name='uq_sharepoint_subscription_user_site'),
        sa.UniqueConstraint('subscription_id')
    )
    op.create_index(op.f('ix_sharepoint_subscriptions_expires_at'), 'sharepoint_subscriptions', ['expires_at'], unique=False)
    op.create_index(op.f('ix_sharepoint_subscriptions_site_id'), 'sharepoint_subscriptions', ['site_id'], unique=False)
    op.create_index(op.f('ix_sharepoint_subscriptions_user_integration_id'), 'sharepoint_subscriptions', ['user_integration_id'], unique=False)

    # 2. Add UUID FK column to integration_knowledge
    op.add_column('integration_knowledge',
                  sa.Column('sharepoint_subscription_id', sa.UUID(), nullable=True))

    # 3. Add foreign key constraint
    op.create_foreign_key(
        'fk_integration_knowledge_sharepoint_subscription',
        'integration_knowledge',
        'sharepoint_subscriptions',
        ['sharepoint_subscription_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    # 1. Drop FK constraint
    op.drop_constraint('fk_integration_knowledge_sharepoint_subscription',
                      'integration_knowledge',
                      type_='foreignkey')

    # 2. Drop sharepoint_subscription_id column
    op.drop_column('integration_knowledge', 'sharepoint_subscription_id')

    # 3. Drop sharepoint_subscriptions table
    op.drop_index(op.f('ix_sharepoint_subscriptions_user_integration_id'), table_name='sharepoint_subscriptions')
    op.drop_index(op.f('ix_sharepoint_subscriptions_site_id'), table_name='sharepoint_subscriptions')
    op.drop_index(op.f('ix_sharepoint_subscriptions_expires_at'), table_name='sharepoint_subscriptions')
    op.drop_table('sharepoint_subscriptions')
