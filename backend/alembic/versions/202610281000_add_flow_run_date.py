"""Add the day a flow run is about, from its form.

Revision ID: 202610281000
Revises: 202610261100
"""

import sqlalchemy as sa

from alembic import op

revision = "202610281000"
down_revision = "202610261100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("flow_runs", sa.Column("run_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("flow_runs", "run_date")
