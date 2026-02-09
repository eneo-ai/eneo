"""add_spaces_user_groups

Revision ID: f0a1b2c3d4e5
Revises: e23b168d0080
Create Date: 2026-01-22 16:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic
revision = 'f0a1b2c3d4e5'
down_revision = 'e23b168d0080'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create spaces_user_groups junction table
    # Allows user groups to be added to spaces with a role
    op.create_table('spaces_user_groups',
        sa.Column('space_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_group_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['space_id'], ['spaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_group_id'], ['user_groups.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('space_id', 'user_group_id')
    )

    # Create index for faster lookups by user_group_id
    op.create_index('ix_spaces_user_groups_user_group_id', 'spaces_user_groups', ['user_group_id'])


def downgrade() -> None:
    op.drop_index('ix_spaces_user_groups_user_group_id', table_name='spaces_user_groups')
    op.drop_table('spaces_user_groups')
