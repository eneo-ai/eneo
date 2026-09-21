"""Distinguish completed crawls with missing resources from incomplete crawls.

Revision ID: 202609101130
Revises: 202609091830
"""

from alembic import op

revision = "202609101130"
down_revision = "202609091830"
branch_labels = None
depends_on = None

_PREVIOUS_CODES = (
    "'dispatch_failed', 'invalid_dispatch', 'worker_interrupted', 'lease_expired', "
    "'remote_unreachable', 'remote_blocked', 'timed_out', 'processing_failed', "
    "'cancelled', 'tenant_quota_exceeded', 'user_quota_exceeded'"
)


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
    # Old summaries cannot prove whether discovery completed; do not reclassify them.
    _replace_failure_constraints(
        f"{_PREVIOUS_CODES}, 'resources_missing'", online_validation=True
    )


def downgrade() -> None:
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    # Keep the recorded explanation and address summary readable in older versions.
    for table in ("crawl_runs", "crawl_attempts", "jobs"):
        op.execute(
            f"UPDATE {table} SET failure_code = 'processing_failed' "
            "WHERE failure_code = 'resources_missing'"
        )
    # Keep rollback atomic if an older migration refuses to discard live work or details.
    _replace_failure_constraints(_PREVIOUS_CODES)
