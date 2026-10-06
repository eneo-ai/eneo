"""accept auto_delete Flow run-history policies and record their deletions

Revision ID: 202610051000
Revises: 202610060100
Create Date: 2026-10-05 10:00:00.000000

- tenants/spaces/flows: the retention mode CHECK accepts 'auto_delete'; the days
  CHECK keeps only the lower bound (the deployment's maximum applies on write).
- gallring_receipts: a Flow run entity and its run_record category, the reasons
  legal_hold / undelivered_audit / unresolved_webhook, the rule levels
  organization / space / flow, the applied rule's scope id and mode, deleted
  rows, the person who started an explicit deletion, and where the file
  reclamation after a run's deletion continues.
- gallring_job_runs: the overdue snapshot written when an execution ends.

Small tables and nullable or defaulted columns: one transaction, no rewrite of
flow_runs. Constraints are added NOT VALID and validated right after. The
downgrade refuses while a stored value needs the new vocabulary.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202610051000"
down_revision: str = "202610060100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POLICY_TABLES = ("tenants", "spaces", "flows")
_OLD_MAX_DAYS = 2555


def _modes(*values: str) -> str:
    return ", ".join(f"'{value}'" for value in values)


_NEW_MODE = (
    "flow_run_history_retention_mode IS NULL OR flow_run_history_retention_mode "
    f"IN ({_modes('auto_delete', 'preserve', 'review_required')})"
)
_OLD_MODE = (
    "flow_run_history_retention_mode IS NULL OR flow_run_history_retention_mode "
    f"IN ({_modes('preserve', 'review_required')})"
)
_NEW_DAYS = (
    "flow_run_history_retention_days IS NULL OR flow_run_history_retention_days >= 1"
)
_OLD_DAYS = (
    "flow_run_history_retention_days IS NULL OR "
    "(flow_run_history_retention_days >= 1 AND "
    f"flow_run_history_retention_days <= {_OLD_MAX_DAYS})"
)

# Receipt vocabulary: (constraint, new predicate, old predicate).
_RECEIPT_CHECKS = (
    (
        "ck_gallring_receipts_entity_kind",
        f"entity_kind IN ({_modes('file_family', 'flow_run')})",
        f"entity_kind IN ({_modes('file_family')})",
    ),
    (
        "ck_gallring_receipts_category",
        f"category IN ({_modes('abandoned_upload', 'run_record', 'template_asset')})",
        f"category IN ({_modes('abandoned_upload', 'template_asset')})",
    ),
    (
        "ck_gallring_receipts_reason",
        "reason IS NULL OR reason IN ("
        + _modes(
            "derived_file_referenced_elsewhere",
            "family_depth_exceeded",
            "family_exceeds_budget",
            "file_referenced_elsewhere",
            "legal_hold",
            "undelivered_audit",
            "unresolved_webhook",
        )
        + ")",
        "reason IS NULL OR reason IN ("
        + _modes(
            "derived_file_referenced_elsewhere",
            "family_depth_exceeded",
            "family_exceeds_budget",
            "file_referenced_elsewhere",
        )
        + ")",
    ),
    (
        "ck_gallring_receipts_policy_source",
        "policy_source IS NULL OR policy_source IN ("
        + _modes("default", "flow", "organization", "space", "tenant")
        + ")",
        f"policy_source IS NULL OR policy_source IN ({_modes('default', 'tenant')})",
    ),
)

_NEW_RECEIPT_CHECKS = (
    ("ck_gallring_receipts_rows", "rows_deleted >= 0"),
    (
        "ck_gallring_receipts_policy_mode",
        "policy_mode IS NULL OR policy_mode IN ("
        + _modes("auto_delete", "preserve", "review_required")
        + ")",
    ),
    (
        "ck_gallring_receipts_triggered_by",
        "triggered_by_user_id IS NULL OR trigger = 'explicit'",
    ),
)

_OVERDUE_CHECK = (
    "ck_gallring_job_runs_overdue",
    "(overdue_observed_at IS NULL) = (overdue_count IS NULL) "
    "AND (overdue_observed_at IS NULL) = (overdue_complete IS NULL) "
    "AND (overdue_count IS NULL OR overdue_count >= 0) "
    "AND COALESCE(overdue_count > 0, false) = "
    "(overdue_oldest_due_at IS NOT NULL)",
)


def _replace_check(table: str, name: str, predicate: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.execute(
        f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" CHECK ({predicate}) NOT VALID'
    )
    op.execute(f'ALTER TABLE "{table}" VALIDATE CONSTRAINT "{name}"')


def _add_check(table: str, name: str, predicate: str) -> None:
    op.execute(
        f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" CHECK ({predicate}) NOT VALID'
    )
    op.execute(f'ALTER TABLE "{table}" VALIDATE CONSTRAINT "{name}"')


def upgrade() -> None:
    # Every statement here takes a brief ACCESS EXCLUSIVE lock: give up instead
    # of queueing writers behind a long transaction.
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table in _POLICY_TABLES:
        _replace_check(table, f"ck_{table}_flow_run_history_retention_mode", _NEW_MODE)
        _replace_check(
            table, f"ck_{table}_flow_run_history_retention_days_range", _NEW_DAYS
        )

    op.add_column(
        "gallring_receipts",
        sa.Column("policy_scope_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "gallring_receipts", sa.Column("policy_mode", sa.String(32), nullable=True)
    )
    op.add_column(
        "gallring_receipts",
        sa.Column(
            "rows_deleted", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
    )
    op.add_column(
        "gallring_receipts",
        sa.Column("triggered_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    for name, predicate, _old in _RECEIPT_CHECKS:
        _replace_check("gallring_receipts", name, predicate)
    for name, predicate in _NEW_RECEIPT_CHECKS:
        _add_check("gallring_receipts", name, predicate)

    for column in (
        sa.Column("overdue_observed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("overdue_count", sa.Integer(), nullable=True),
        sa.Column("overdue_complete", sa.Boolean(), nullable=True),
        sa.Column("overdue_oldest_due_at", sa.TIMESTAMP(timezone=True), nullable=True),
    ):
        op.add_column("gallring_job_runs", column)
    _add_check("gallring_job_runs", *_OVERDUE_CHECK)


_NEEDS_NEW_VOCABULARY = " UNION ALL ".join(
    [
        *(
            f"SELECT 1 FROM {table} WHERE flow_run_history_retention_mode = "
            f"'auto_delete' OR flow_run_history_retention_days > {_OLD_MAX_DAYS}"
            for table in _POLICY_TABLES
        ),
        "SELECT 1 FROM gallring_receipts WHERE entity_kind = 'flow_run' "
        "OR category = 'run_record' OR reason IN "
        f"({_modes('legal_hold', 'undelivered_audit', 'unresolved_webhook')}) "
        f"OR policy_source IN ({_modes('flow', 'organization', 'space')})",
    ]
)


def downgrade() -> None:
    if not op.get_context().as_sql:
        blocked = (
            op.get_bind()
            .execute(sa.text(f"SELECT EXISTS ({_NEEDS_NEW_VOCABULARY})"))
            .scalar()
        )
        if blocked:
            raise RuntimeError(
                "Cannot downgrade 202610051000: auto_delete policies, policies "
                f"longer than {_OLD_MAX_DAYS} days or Flow run deletion receipts "
                "are stored. Change those policies first; receipts are proof and "
                "are not removed by a downgrade."
            )
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint(_OVERDUE_CHECK[0], "gallring_job_runs", type_="check")
    for column in (
        "overdue_oldest_due_at",
        "overdue_complete",
        "overdue_count",
        "overdue_observed_at",
    ):
        op.drop_column("gallring_job_runs", column)

    for name, _predicate in reversed(_NEW_RECEIPT_CHECKS):
        op.drop_constraint(name, "gallring_receipts", type_="check")
    for name, _new, old in _RECEIPT_CHECKS:
        _replace_check("gallring_receipts", name, old)
    for column in (
        "triggered_by_user_id",
        "rows_deleted",
        "policy_mode",
        "policy_scope_id",
    ):
        op.drop_column("gallring_receipts", column)

    for table in _POLICY_TABLES:
        _replace_check(
            table, f"ck_{table}_flow_run_history_retention_days_range", _OLD_DAYS
        )
        _replace_check(table, f"ck_{table}_flow_run_history_retention_mode", _OLD_MODE)
