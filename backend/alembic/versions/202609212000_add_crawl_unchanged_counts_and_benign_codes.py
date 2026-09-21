"""Record unchanged crawl resources and name benign partial outcomes.

Revision ID: 202609212000
Revises: 202609211200

crawl_runs gains pages_unchanged and files_unchanged: resources the crawler
verified but did not re-index (HTTP 304 or identical content). Older rows keep
NULL, which the API reports as "not recorded". From this revision on,
pages_crawled counts only pages that were actually (re)indexed; before it,
identical-content pages were counted as crawled.

Two failure codes join the check constraints: page_limit_reached (a healthy
crawl truncated at the configured page limit) and content_skipped (a healthy
crawl where some pages had no indexable content). Both used to fall through to
processing_failed.
"""

import sqlalchemy as sa

from alembic import op

revision = "202609212000"
down_revision = "202609211200"
branch_labels = None
depends_on = None

_PREVIOUS_CODES = (
    "'dispatch_failed', 'invalid_dispatch', 'worker_interrupted', 'lease_expired', "
    "'remote_unreachable', 'remote_blocked', 'timed_out', 'processing_failed', "
    "'cancelled', 'tenant_quota_exceeded', 'user_quota_exceeded', 'resources_missing'"
)
_NEW_CODES = f"{_PREVIOUS_CODES}, 'page_limit_reached', 'content_skipped'"
_COUNTERS = ("pages_unchanged", "files_unchanged")


def _replace_failure_constraints(
    codes: str, *, online_validation: bool = False
) -> None:
    for table in ("crawl_runs", "crawl_attempts"):
        name = f"ck_{table}_failure_code"
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(
            name,
            table,
            f"failure_code IS NULL OR failure_code IN ({codes})",
            postgresql_not_valid=online_validation,
        )
    if online_validation:
        # Release the DDL locks before scanning history during a live upgrade.
        with op.get_context().autocommit_block():
            for table in ("crawl_runs", "crawl_attempts"):
                op.execute(
                    f"ALTER TABLE {table} VALIDATE CONSTRAINT ck_{table}_failure_code"
                )


def upgrade() -> None:
    for column in _COUNTERS:
        op.add_column("crawl_runs", sa.Column(column, sa.Integer(), nullable=True))
        op.create_check_constraint(
            f"ck_crawl_runs_{column}",
            "crawl_runs",
            f"{column} IS NULL OR {column} >= 0",
        )
    _replace_failure_constraints(_NEW_CODES, online_validation=True)


def downgrade() -> None:
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    # Older versions do not know the benign codes; keep their runs readable.
    for table in ("crawl_runs", "crawl_attempts", "jobs"):
        op.execute(
            f"UPDATE {table} SET failure_code = 'processing_failed' "
            "WHERE failure_code IN ('page_limit_reached', 'content_skipped')"
        )
    _replace_failure_constraints(_PREVIOUS_CODES)
    for column in reversed(_COUNTERS):
        op.drop_constraint(f"ck_crawl_runs_{column}", "crawl_runs", type_="check")
        op.drop_column("crawl_runs", column)
