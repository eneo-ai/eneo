"""Add review checkpoint expiry lifecycle.

Revision ID: 20260514_review_expiry
Revises: 20260508_review_checkpoint_ui
Create Date: 2026-05-14 12:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260514_review_expiry"
down_revision = "20260508_review_checkpoint_ui"
branch_labels = None
depends_on = None

FLOW_RUN_TERMINAL_STATUSES = ("completed", "failed", "cancelled")
OLD_REVIEW_CHECKPOINT_STATES = (
    "awaiting_review",
    "edited",
    "approved",
    "rejected",
    "resumed",
    "cancelled",
)
REVIEW_CHECKPOINT_STATES = (
    "awaiting_review",
    "edited",
    "approved",
    "rejected",
    "resumed",
    "cancelled",
    "expired",
)
REVIEW_CHECKPOINT_RECONCILABLE_STATES = ("awaiting_review", "edited")
REVIEW_CHECKPOINT_EXPIRY_INDEX_PREDICATE = "state IN ('awaiting_review', 'edited')"
OLD_FLOW_RUN_LIFECYCLE_SOURCES = (
    "executor_completed",
    "executor_failed",
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
)
FLOW_RUN_LIFECYCLE_SOURCES = (
    "executor_completed",
    "executor_failed",
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
OLD_FLOW_RUN_AUDIT_TARGET_STATUSES = tuple(
    dict.fromkeys(FLOW_RUN_TERMINAL_STATUSES + OLD_REVIEW_CHECKPOINT_STATES)
)
FLOW_RUN_AUDIT_TARGET_STATUSES = tuple(
    dict.fromkeys(FLOW_RUN_TERMINAL_STATUSES + REVIEW_CHECKPOINT_STATES)
)


def _check_values(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.add_column(
        "flow_run_review_checkpoints",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "flow_run_review_checkpoints",
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint(
        "ck_flow_run_review_checkpoints_state",
        "flow_run_review_checkpoints",
        type_="check",
    )
    op.create_check_constraint(
        "ck_flow_run_review_checkpoints_state",
        "flow_run_review_checkpoints",
        f"state IN ({_check_values(REVIEW_CHECKPOINT_STATES)})",
    )
    op.create_index(
        "ix_flow_run_review_checkpoints_tenant_expires_at_reconcilable",
        "flow_run_review_checkpoints",
        ["tenant_id", "expires_at"],
        postgresql_where=sa.text(REVIEW_CHECKPOINT_EXPIRY_INDEX_PREDICATE),
    )

    op.drop_constraint(
        "ck_flow_run_audit_outbox_target_status",
        "flow_run_audit_outbox",
        type_="check",
    )
    op.drop_constraint(
        "ck_flow_run_audit_outbox_source",
        "flow_run_audit_outbox",
        type_="check",
    )
    op.create_check_constraint(
        "ck_flow_run_audit_outbox_target_status",
        "flow_run_audit_outbox",
        f"target_status IN ({_check_values(FLOW_RUN_AUDIT_TARGET_STATUSES)})",
    )
    op.create_check_constraint(
        "ck_flow_run_audit_outbox_source",
        "flow_run_audit_outbox",
        f"source IN ({_check_values(FLOW_RUN_LIFECYCLE_SOURCES)})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_flow_run_audit_outbox_source",
        "flow_run_audit_outbox",
        type_="check",
    )
    op.drop_constraint(
        "ck_flow_run_audit_outbox_target_status",
        "flow_run_audit_outbox",
        type_="check",
    )
    op.create_check_constraint(
        "ck_flow_run_audit_outbox_target_status",
        "flow_run_audit_outbox",
        f"target_status IN ({_check_values(OLD_FLOW_RUN_AUDIT_TARGET_STATUSES)})",
    )
    op.create_check_constraint(
        "ck_flow_run_audit_outbox_source",
        "flow_run_audit_outbox",
        f"source IN ({_check_values(OLD_FLOW_RUN_LIFECYCLE_SOURCES)})",
    )

    op.drop_index(
        "ix_flow_run_review_checkpoints_tenant_expires_at_reconcilable",
        table_name="flow_run_review_checkpoints",
    )
    op.drop_constraint(
        "ck_flow_run_review_checkpoints_state",
        "flow_run_review_checkpoints",
        type_="check",
    )
    op.create_check_constraint(
        "ck_flow_run_review_checkpoints_state",
        "flow_run_review_checkpoints",
        f"state IN ({_check_values(OLD_REVIEW_CHECKPOINT_STATES)})",
    )
    op.drop_column("flow_run_review_checkpoints", "expired_at")
    op.drop_column("flow_run_review_checkpoints", "expires_at")
