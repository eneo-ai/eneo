"""add_jsonb_index_for_action_overrides

Revision ID: d5c001343e52
Revises: c04ddeaf1c5f
Create Date: 2025-11-17 22:02:09.889426

Add GIN index on action_overrides JSONB column for faster key lookups.
This improves performance when checking specific action overrides.
"""

from alembic import op


# revision identifiers, used by Alembic
revision = 'd5c001343e52'
down_revision = 'c04ddeaf1c5f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add GIN index for JSONB action_overrides column."""
    # Create GIN index for faster JSONB key lookups
    # This speeds up queries like: WHERE action_overrides ? 'action_name'
    op.create_index(
        'idx_audit_category_config_action_overrides_gin',
        'audit_category_config',
        ['action_overrides'],
        unique=False,
        postgresql_using='gin'
    )


def downgrade() -> None:
    """Remove GIN index from action_overrides column."""
    op.drop_index(
        'idx_audit_category_config_action_overrides_gin',
        table_name='audit_category_config',
        postgresql_using='gin'
    )