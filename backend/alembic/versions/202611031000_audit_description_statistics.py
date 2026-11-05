"""keep planner statistics on lower(audit_logs.description)

The description search filters on lower(description), the expression of the
trigram index. That index is partial, and the planner ignores statistics of
partial indexes, so it had none for the expression and chose the index even
for terms matching most of the log. Expression statistics need Postgres 14;
on older servers this migration does nothing.

ANALYZE builds the statistics now instead of at the next autoanalyze. It reads
a fixed-size sample (30,000 rows at the default statistics target), so its cost
does not grow with the log: 0.3 s at 1M rows. Naming only description skips
redoing the statistics of the other columns.

Revision ID: 202611031000
Revises: 202611030830
Create Date: 2026-11-03 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202611031000"
down_revision: str | None = "202611030830"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF current_setting('server_version_num')::int >= 140000 THEN
                EXECUTE 'CREATE STATISTICS IF NOT EXISTS
                    audit_logs_lower_description_stat
                    ON (lower(description)) FROM audit_logs';
                EXECUTE 'ANALYZE audit_logs (description)';
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP STATISTICS IF EXISTS audit_logs_lower_description_stat")
