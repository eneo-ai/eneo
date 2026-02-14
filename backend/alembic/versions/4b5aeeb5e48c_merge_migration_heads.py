"""merge migration heads
Revision ID: 4b5aeeb5e48c
Revises: remove_legacy_templates, add_activity_indexes
Create Date: 2026-02-02 09:42:39.395648
"""



# revision identifiers, used by Alembic
revision = '4b5aeeb5e48c'
down_revision = ('remove_legacy_templates', 'add_activity_indexes')
branch_labels = None
depends_on = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass