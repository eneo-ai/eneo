"""Create integration_knowledge_spaces junction table for knowledge distribution

Revision ID: 202510301145
Revises: 202510301130
Create Date: 2025-10-30 11:45:00.000000

This table allows integration knowledge created on organization spaces to be
distributed to all child spaces, similar to how collections and websites work.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision = '202510301145'
down_revision = '202510301130'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create integration_knowledge_spaces table."""
    op.create_table(
        'integration_knowledge_spaces',
        sa.Column('integration_knowledge_id', sa.UUID(), nullable=False),
        sa.Column('space_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ['integration_knowledge_id'],
            ['integration_knowledge.id'],
            ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['space_id'],
            ['spaces.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('integration_knowledge_id', 'space_id'),
    )
    op.create_index(
        'ix_integration_knowledge_spaces_integration_knowledge_id',
        'integration_knowledge_spaces',
        ['integration_knowledge_id'],
    )
    op.create_index(
        'ix_integration_knowledge_spaces_space_id',
        'integration_knowledge_spaces',
        ['space_id'],
    )


def downgrade() -> None:
    """Drop integration_knowledge_spaces table."""
    op.drop_index(
        'ix_integration_knowledge_spaces_space_id',
        table_name='integration_knowledge_spaces'
    )
    op.drop_index(
        'ix_integration_knowledge_spaces_integration_knowledge_id',
        table_name='integration_knowledge_spaces'
    )
    op.drop_table('integration_knowledge_spaces')
