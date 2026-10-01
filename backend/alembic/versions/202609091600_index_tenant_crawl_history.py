"""Bound tenant crawl overview reads by completion time.

Revision ID: 202609091600
Revises: 202609091300
"""

import sqlalchemy as sa

from alembic import op

revision = "202609091600"
down_revision = "202609091300"
branch_labels = None
depends_on = None

_INDEX = "ix_crawl_runs_tenant_finished"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # A cancelled concurrent build can leave an invalid index behind.
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        op.create_index(
            _INDEX,
            "crawl_runs",
            ["tenant_id", "finished_at", "id"],
            postgresql_where=sa.text("phase = 'terminal'"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    # Keep removal in the rollback transaction: lower revisions may refuse to
    # discard recorded failure addresses or change schema while work is active.
    op.drop_index(_INDEX, table_name="crawl_runs")
