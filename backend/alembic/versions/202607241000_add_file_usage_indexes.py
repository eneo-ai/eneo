"""add reverse indexes for File usage checks

Revision ID: 202607241000
Revises: 202607231700
Create Date: 2026-07-24 10:00:00.000000

Each junction-table primary key starts with its product owner ID. File deletion
preview instead filters by ``file_id``, so these reverse indexes keep usage
checks proportional to matching relations. They are built concurrently to
avoid blocking attachment writes during an upgrade.

If a concurrent build fails, rerun the migration. The explicit drop removes
any invalid index left by PostgreSQL before the build is retried.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607241000"
down_revision: str | None = "202607231700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = (
    ("ix_questions_files_file_id", "questions_files"),
    ("ix_assistants_files_file_id", "assistants_files"),
    ("ix_apps_files_file_id", "apps_files"),
    ("ix_app_runs_files_file_id", "app_runs_files"),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for index_name, table_name in _INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}")
            op.execute(
                f"CREATE INDEX CONCURRENTLY {index_name} ON {table_name} (file_id)"
            )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for index_name, _table_name in reversed(_INDEXES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}")
