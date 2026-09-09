"""Read active tenant crawls in creation order without sorting the backlog.

Revision ID: 202609091830
Revises: 202609091600
"""

import sqlalchemy as sa

from alembic import op

revision = "202609091830"
down_revision = "202609091600"
branch_labels = None
depends_on = None

_INDEX = "ix_crawl_runs_tenant_active_created"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # A cancelled concurrent build can leave an invalid index behind.
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        op.create_index(
            _INDEX,
            "crawl_runs",
            ["tenant_id", "created_at", "id"],
            postgresql_where=sa.text("phase <> 'terminal'"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    # Lower revisions may refuse a rollback with live work or saved failures.
    # Keep index removal in their transaction so refusal preserves the schema.
    op.drop_index(_INDEX, table_name="crawl_runs")
