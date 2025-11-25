"""sharepoint site level subscriptions

Revision ID: 202511061533
Revises: 202411041401
Create Date: 2025-11-06 15:33:00.000000

Refactors SharePoint webhook subscriptions to be site-level (shared across integrations)
instead of per-integration. This reduces duplicate webhooks and simplifies management.

Changes:
1. Creates new sharepoint_subscriptions table
2. Migrates existing subscription data (deduplicates by site)
3. Adds FK from integration_knowledge to sharepoint_subscriptions
4. Removes old subscription columns from integration_knowledge
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '202511061533'
down_revision: Union[str, None] = '202411041401'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create new sharepoint_subscriptions table
    op.create_table(
        'sharepoint_subscriptions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
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

    # 2. Migrate existing subscription data
    # This is a complex data migration that:
    # - Groups integration_knowledge by (user_integration_id, site_id)
    # - For each group, picks the subscription with longest expiration
    # - Creates one sharepoint_subscription per group
    # - Links all integration_knowledge in group to that subscription

    conn = op.get_bind()

    # Get all unique (user_integration_id, site_id) combinations with subscriptions
    result = conn.execute(sa.text("""
        SELECT DISTINCT
            ik.user_integration_id,
            ik.site_id
        FROM integration_knowledge ik
        WHERE ik.sharepoint_subscription_id IS NOT NULL
          AND ik.site_id IS NOT NULL
    """))

    site_groups = result.fetchall()

    # For each site group, find the subscription with longest expiration and create shared subscription
    for user_integration_id, site_id in site_groups:
        # Find the integration_knowledge with longest-lived subscription for this site
        best_knowledge = conn.execute(sa.text("""
            SELECT
                id,
                sharepoint_subscription_id,
                sharepoint_subscription_expires_at
            FROM integration_knowledge
            WHERE user_integration_id = :user_integration_id
              AND site_id = :site_id
              AND sharepoint_subscription_id IS NOT NULL
            ORDER BY sharepoint_subscription_expires_at DESC NULLS LAST
            LIMIT 1
        """), {
            'user_integration_id': str(user_integration_id),
            'site_id': site_id
        }).fetchone()

        if not best_knowledge:
            continue

        knowledge_id, subscription_id, expires_at = best_knowledge

        # Get drive_id from site_id (we need to infer it or set a placeholder)
        # Since we don't have drive_id stored, we'll need to re-resolve it later
        # For now, use a placeholder that will be updated on first renewal
        drive_id_placeholder = f"drive_for_{site_id[:20]}"

        # Insert into sharepoint_subscriptions
        new_subscription_result = conn.execute(sa.text("""
            INSERT INTO sharepoint_subscriptions
                (id, user_integration_id, site_id, subscription_id, drive_id, expires_at, created_at)
            VALUES
                (gen_random_uuid(), :user_integration_id, :site_id, :subscription_id, :drive_id, :expires_at, now())
            RETURNING id
        """), {
            'user_integration_id': str(user_integration_id),
            'site_id': site_id,
            'subscription_id': subscription_id,
            'drive_id': drive_id_placeholder,
            'expires_at': expires_at or 'now()'
        })

        new_subscription_id = new_subscription_result.fetchone()[0]

        # Update all integration_knowledge for this site to reference the new shared subscription
        conn.execute(sa.text("""
            UPDATE integration_knowledge
            SET sharepoint_subscription_id = :new_subscription_id
            WHERE user_integration_id = :user_integration_id
              AND site_id = :site_id
        """), {
            'new_subscription_id': str(new_subscription_id),
            'user_integration_id': str(user_integration_id),
            'site_id': site_id
        })

    # 3. Add new FK column to integration_knowledge (temporarily as text, will convert to UUID FK)
    # First rename old column to preserve data temporarily
    op.alter_column('integration_knowledge', 'sharepoint_subscription_id',
                    new_column_name='sharepoint_subscription_id_old',
                    existing_type=sa.Text(),
                    existing_nullable=True)

    # Add new UUID FK column
    op.add_column('integration_knowledge',
                  sa.Column('sharepoint_subscription_id', sa.UUID(), nullable=True))

    # Copy migrated UUIDs from text column to UUID column
    conn.execute(sa.text("""
        UPDATE integration_knowledge
        SET sharepoint_subscription_id = sharepoint_subscription_id_old::uuid
        WHERE sharepoint_subscription_id_old IS NOT NULL
          AND sharepoint_subscription_id_old ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    """))

    # 4. Add foreign key constraint
    op.create_foreign_key(
        'fk_integration_knowledge_sharepoint_subscription',
        'integration_knowledge',
        'sharepoint_subscriptions',
        ['sharepoint_subscription_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # 5. Drop old columns
    op.drop_column('integration_knowledge', 'sharepoint_subscription_id_old')
    op.drop_column('integration_knowledge', 'sharepoint_subscription_expires_at')


def downgrade() -> None:
    # 1. Add back old columns
    op.add_column('integration_knowledge',
                  sa.Column('sharepoint_subscription_expires_at',
                           postgresql.TIMESTAMP(timezone=True),
                           nullable=True))
    op.add_column('integration_knowledge',
                  sa.Column('sharepoint_subscription_id_old', sa.TEXT(), nullable=True))

    # 2. Migrate data back (best effort - copy subscription_id from sharepoint_subscriptions)
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE integration_knowledge ik
        SET
            sharepoint_subscription_id_old = ss.subscription_id,
            sharepoint_subscription_expires_at = ss.expires_at
        FROM sharepoint_subscriptions ss
        WHERE ik.sharepoint_subscription_id = ss.id
    """))

    # 3. Drop FK and new column
    op.drop_constraint('fk_integration_knowledge_sharepoint_subscription',
                      'integration_knowledge',
                      type_='foreignkey')
    op.drop_column('integration_knowledge', 'sharepoint_subscription_id')

    # 4. Restore old column name
    op.alter_column('integration_knowledge', 'sharepoint_subscription_id_old',
                    new_column_name='sharepoint_subscription_id',
                    existing_type=sa.TEXT(),
                    existing_nullable=True)

    # 5. Drop sharepoint_subscriptions table
    op.drop_index(op.f('ix_sharepoint_subscriptions_user_integration_id'), table_name='sharepoint_subscriptions')
    op.drop_index(op.f('ix_sharepoint_subscriptions_site_id'), table_name='sharepoint_subscriptions')
    op.drop_index(op.f('ix_sharepoint_subscriptions_expires_at'), table_name='sharepoint_subscriptions')
    op.drop_table('sharepoint_subscriptions')
