"""Allow tenant and user quota failures in crawl history.

Revision ID: 202609091230
Revises: 202609071200
"""

from alembic import op

revision = "202609091230"
down_revision = "202609071200"
branch_labels = None
depends_on = None

_PREVIOUS_CODES = (
    "'dispatch_failed', 'invalid_dispatch', 'worker_interrupted', 'lease_expired', "
    "'remote_unreachable', 'remote_blocked', 'timed_out', 'processing_failed', "
    "'cancelled'"
)
_QUOTA_CODES = "'tenant_quota_exceeded', 'user_quota_exceeded'"


def _replace_failure_constraints(codes: str) -> None:
    for table in ("crawl_runs", "crawl_attempts"):
        name = f"ck_{table}_failure_code"
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(
            name,
            table,
            f"failure_code IS NULL OR failure_code IN ({codes})",
        )


def upgrade() -> None:
    _replace_failure_constraints(f"{_PREVIOUS_CODES}, {_QUOTA_CODES}")


def downgrade() -> None:
    # Resolve deferred lifecycle constraints before altering the updated tables.
    op.execute("SET CONSTRAINTS ALL IMMEDIATE")
    # Older application versions need their known codes. The quota-specific
    # explanation and page failure summary remain available in the history.
    for table, fallback in (
        ("crawl_runs", "processing_failed"),
        ("crawl_attempts", "processing_failed"),
        ("jobs", "quota_exceeded"),
    ):
        op.execute(
            f"UPDATE {table} SET failure_code = '{fallback}' "
            f"WHERE failure_code IN ({_QUOTA_CODES})"
        )
    _replace_failure_constraints(_PREVIOUS_CODES)
