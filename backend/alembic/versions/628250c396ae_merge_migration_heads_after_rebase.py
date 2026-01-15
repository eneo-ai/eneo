"""merge migration heads after rebase
Revision ID: 628250c396ae
Revises: retention_perf_indexes, bdcbd045fbde
Create Date: 2025-12-06 16:43:52.252994
"""



# revision identifiers, used by Alembic
revision = '628250c396ae'
down_revision = ('retention_perf_indexes', 'bdcbd045fbde')
branch_labels = None
depends_on = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass