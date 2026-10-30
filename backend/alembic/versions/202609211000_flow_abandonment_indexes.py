"""Index abandoned waits and permit their audit lifecycle source.

Revision ID: 202609211000
Revises: 202609201300
"""

import re

import sqlalchemy as sa

from alembic import op

revision = "202609211000"
down_revision = "202609201300"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_flow_run_audit_outbox_source"
_TABLE = "flow_run_audit_outbox"
_OLD_SOURCES = (
    "executor_completed",
    "executor_failed",
    "dispatch_failure",
    "flow_deleted",
    "definition_checksum_mismatch",
    "invalid_flow_definition",
    "assistant_snapshot_drift",
    "step_missing",
    "task_timeout",
    "task_failure",
    "missing_principal",
    "stale_running_reconciler",
    "user_cancel",
    "review_rejected",
    "review_checkpoint_opened",
    "review_checkpoint_edited",
    "review_checkpoint_approved",
    "review_checkpoint_rejected",
    "review_checkpoint_resumed",
    "review_checkpoint_cancelled",
    "review_expired",
    "review_checkpoint_expired",
)
_NEW_SOURCES = (
    "executor_completed",
    "executor_failed",
    "dispatch_failure",
    "flow_deleted",
    "definition_checksum_mismatch",
    "invalid_flow_definition",
    "assistant_snapshot_drift",
    "step_missing",
    "task_timeout",
    "task_failure",
    "missing_principal",
    "stale_running_reconciler",
    "abandonment_reconciler",
    "user_cancel",
    "review_rejected",
    "review_checkpoint_opened",
    "review_checkpoint_edited",
    "review_checkpoint_approved",
    "review_checkpoint_rejected",
    "review_checkpoint_resumed",
    "review_checkpoint_cancelled",
    "review_expired",
    "review_checkpoint_expired",
)

_INDEXES = (
    (
        "ix_flow_runs_exhausted_dispatch_wait",
        "flow_runs",
        ["dispatch_pending_since", "id"],
        ["tenant_id", "revision"],
        "status = 'queued' AND dispatch_exhausted_at IS NOT NULL",
    ),
    (
        "ix_flow_runs_awaiting_review_created",
        "flow_runs",
        ["created_at", "id"],
        ["tenant_id", "revision"],
        "status = 'awaiting_review'",
    ),
    (
        "ix_flow_review_approved_wait",
        "flow_run_review_checkpoints",
        ["approved_at", "flow_run_id"],
        ["tenant_id", "id"],
        "state = 'approved'",
    ),
)


def _install_source_constraint(sources: tuple[str, ...]) -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    constraint = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT convalidated, pg_get_constraintdef(oid) AS definition "
                "FROM pg_constraint WHERE conrelid = 'flow_run_audit_outbox'::regclass "
                "AND conname = :name"
            ),
            {"name": _CONSTRAINT},
        )
        .mappings()
        .one_or_none()
    )
    matches = constraint is not None and set(
        re.findall(r"'([^']*)'", constraint["definition"])
    ) == set(sources)
    if matches and constraint["convalidated"]:
        return
    if not matches:
        if constraint is not None:
            op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
        values = ",".join(f"'{source}'" for source in sources)
        op.execute(
            f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CONSTRAINT} "
            f"CHECK (source IN ({values})) NOT VALID"
        )
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            op.execute(f"ALTER TABLE {_TABLE} VALIDATE CONSTRAINT {_CONSTRAINT}")
        finally:
            op.execute("RESET lock_timeout")


def upgrade() -> None:
    _install_source_constraint(_NEW_SOURCES)
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            for name, table, columns, include, predicate in _INDEXES:
                valid = (
                    op.get_bind()
                    .execute(
                        sa.text(
                            "SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)"
                        ),
                        {"name": name},
                    )
                    .scalar()
                )
                if valid is False:
                    op.drop_index(name, table_name=table, postgresql_concurrently=True)
                op.create_index(
                    name,
                    table,
                    columns,
                    postgresql_include=include,
                    postgresql_where=sa.text(predicate),
                    postgresql_concurrently=True,
                    if_not_exists=True,
                )
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(f"LOCK TABLE {_TABLE} IN ACCESS EXCLUSIVE MODE")
    retained = (
        op.get_bind()
        .execute(
            sa.text(
                f"SELECT EXISTS (SELECT 1 FROM {_TABLE} "
                "WHERE source = 'abandonment_reconciler')"
            )
        )
        .scalar_one()
    )
    if retained:
        raise RuntimeError(
            "Refusing to downgrade 202609211000: abandonment audit records "
            "cannot be represented by the previous source constraint."
        )
    _install_source_constraint(_OLD_SOURCES)
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            for name, table, *_ in reversed(_INDEXES):
                op.drop_index(
                    name,
                    table_name=table,
                    postgresql_concurrently=True,
                    if_exists=True,
                )
        finally:
            op.execute("RESET lock_timeout")
