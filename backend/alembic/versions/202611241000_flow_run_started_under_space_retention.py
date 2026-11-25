"""Mark a Flow run that starts while its space has a time

Only a marked run is removed automatically. Runs that exist before the upgrade
started under other rules, so they stay unmarked: the column gets a constant
default and no backfill.

Revision ID: 202611241000
Revises: 202611231030
"""

import sqlalchemy as sa

from alembic import op

revision = "202611241000"
down_revision = "202611231030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "flow_runs",
        sa.Column(
            "started_under_space_retention",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("flow_runs", "started_under_space_retention")
