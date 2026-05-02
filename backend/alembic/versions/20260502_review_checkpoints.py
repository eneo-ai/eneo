"""Add flow run review checkpoints.

Revision ID: 20260502_review_checkpoints
Revises: 20260502_rerun_runtime_lineage
Create Date: 2026-05-02 16:40:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260502_review_checkpoints"
down_revision = "20260502_rerun_runtime_lineage"
branch_labels = None
depends_on = None

FLOW_RUN_STATUSES = (
    "queued",
    "running",
    "awaiting_review",
    "completed",
    "failed",
    "cancelled",
)
FLOW_RUN_TERMINAL_STATUSES = ("completed", "failed", "cancelled")
REVIEW_CHECKPOINT_STATES = (
    "awaiting_review",
    "edited",
    "approved",
    "rejected",
    "resumed",
    "cancelled",
)
FLOW_RUN_AUDIT_TARGET_STATUSES = tuple(
    dict.fromkeys(FLOW_RUN_TERMINAL_STATUSES + REVIEW_CHECKPOINT_STATES)
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
    "dispatch_failure",
    "review_rejected",
    "review_checkpoint_opened",
    "review_checkpoint_edited",
    "review_checkpoint_approved",
    "review_checkpoint_rejected",
    "review_checkpoint_resumed",
    "review_checkpoint_cancelled",
)
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
    "dispatch_failure",
)


def _check_values(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.drop_constraint("ck_flow_runs_status", "flow_runs", type_="check")
    op.create_check_constraint(
        "ck_flow_runs_status",
        "flow_runs",
        f"status IN ({_check_values(FLOW_RUN_STATUSES)})",
    )

    op.create_table(
        "flow_run_review_checkpoints",
        sa.Column(
            "tenant_id",
            sa.UUID(),
            sa.ForeignKey(
                "tenants.id",
                ondelete="CASCADE",
                name="fk_review_checkpoints_tenant",
            ),
            nullable=False,
        ),
        sa.Column(
            "flow_id",
            sa.UUID(),
            sa.ForeignKey(
                "flows.id",
                ondelete="CASCADE",
                name="fk_review_checkpoints_flow",
            ),
            nullable=False,
        ),
        sa.Column("flow_run_id", sa.UUID(), nullable=False),
        sa.Column("step_id", sa.UUID(), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            sa.String(length=32),
            server_default="awaiting_review",
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("original_payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("current_payload_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "requester_user_id",
            sa.UUID(),
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="fk_review_checkpoints_requester_user",
            ),
            nullable=True,
        ),
        sa.Column("requester_principal_type", sa.String(length=32), nullable=False),
        sa.Column(
            "decided_by_user_id",
            sa.UUID(),
            sa.ForeignKey(
                "users.id",
                ondelete="SET NULL",
                name="fk_review_checkpoints_decided_by_user",
            ),
            nullable=True,
        ),
        sa.Column("decided_by_principal_type", sa.String(length=32), nullable=True),
        sa.Column("next_step_ids_json", postgresql.JSONB(), nullable=True),
        sa.Column("resume_idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.func.gen_random_uuid(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"state IN ({_check_values(REVIEW_CHECKPOINT_STATES)})",
            name="ck_flow_run_review_checkpoints_state",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_flow_run_review_checkpoints_revision",
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_flow_run_review_checkpoints_schema_version",
        ),
        sa.CheckConstraint(
            "requester_principal_type IN ('user','service_key')",
            name="ck_flow_run_review_checkpoints_requester_principal",
        ),
        sa.CheckConstraint(
            "decided_by_principal_type IS NULL "
            "OR decided_by_principal_type IN ('user','service_key')",
            name="ck_flow_run_review_checkpoints_decider_principal",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "tenant_id"],
            ["flow_runs.id", "flow_runs.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_run_review_checkpoints_run_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["flow_run_id", "flow_id"],
            ["flow_runs.id", "flow_runs.flow_id"],
            ondelete="CASCADE",
            name="fk_flow_run_review_checkpoints_run_flow",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "flow_run_id",
            "step_id",
            "attempt_no",
            name="uq_flow_run_review_checkpoints_run_step_attempt",
        ),
    )
    op.create_index(
        "ix_flow_run_review_checkpoints_flow_id",
        "flow_run_review_checkpoints",
        ["flow_id"],
    )
    op.create_index(
        "ix_flow_run_review_checkpoints_flow_run_id",
        "flow_run_review_checkpoints",
        ["flow_run_id"],
    )
    op.create_index(
        "ix_flow_run_review_checkpoints_tenant_id",
        "flow_run_review_checkpoints",
        ["tenant_id"],
    )
    op.create_index(
        "uq_flow_run_review_checkpoints_one_active_per_run",
        "flow_run_review_checkpoints",
        ["flow_run_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('awaiting_review', 'edited', 'approved')"),
    )
    op.create_index(
        "uq_flow_run_review_checkpoints_resume_key",
        "flow_run_review_checkpoints",
        ["tenant_id", "flow_run_id", "resume_idempotency_key"],
        unique=True,
        postgresql_where=sa.text("resume_idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "ix_flow_run_review_checkpoints_run_step_attempt",
        "flow_run_review_checkpoints",
        ["flow_run_id", "step_id", "attempt_no"],
    )
    op.create_index(
        "ix_flow_run_review_checkpoints_tenant_created_at",
        "flow_run_review_checkpoints",
        ["tenant_id", "created_at"],
    )

    op.add_column(
        "flow_run_audit_outbox",
        sa.Column("review_checkpoint_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "flow_run_audit_outbox",
        sa.Column("checkpoint_revision", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_flow_run_audit_outbox_review_checkpoint_id",
        "flow_run_audit_outbox",
        ["review_checkpoint_id"],
    )
    op.create_foreign_key(
        "fk_flow_run_audit_outbox_review_checkpoint",
        "flow_run_audit_outbox",
        "flow_run_review_checkpoints",
        ["review_checkpoint_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        "uq_flow_run_audit_outbox_run_revision",
        "flow_run_audit_outbox",
        type_="unique",
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
    op.create_index(
        "uq_flow_run_audit_outbox_run_revision",
        "flow_run_audit_outbox",
        ["flow_run_id", "run_revision"],
        unique=True,
        postgresql_where=sa.text("review_checkpoint_id IS NULL"),
    )
    op.create_index(
        "uq_flow_run_audit_outbox_checkpoint_revision",
        "flow_run_audit_outbox",
        ["review_checkpoint_id", "checkpoint_revision"],
        unique=True,
        postgresql_where=sa.text("review_checkpoint_id IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_flow_run_audit_outbox_target_status",
        "flow_run_audit_outbox",
        f"target_status IN ({_check_values(FLOW_RUN_AUDIT_TARGET_STATUSES)})",
    )
    op.create_check_constraint(
        "ck_flow_run_audit_outbox_checkpoint_key",
        "flow_run_audit_outbox",
        "("
        "(review_checkpoint_id IS NULL AND checkpoint_revision IS NULL) "
        "OR "
        "(review_checkpoint_id IS NOT NULL AND checkpoint_revision IS NOT NULL)"
        ")",
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
        "ck_flow_run_audit_outbox_checkpoint_key",
        "flow_run_audit_outbox",
        type_="check",
    )
    op.drop_constraint(
        "ck_flow_run_audit_outbox_target_status",
        "flow_run_audit_outbox",
        type_="check",
    )
    op.drop_index(
        "uq_flow_run_audit_outbox_checkpoint_revision",
        table_name="flow_run_audit_outbox",
    )
    op.drop_index(
        "uq_flow_run_audit_outbox_run_revision",
        table_name="flow_run_audit_outbox",
    )
    op.create_unique_constraint(
        "uq_flow_run_audit_outbox_run_revision",
        "flow_run_audit_outbox",
        ["flow_run_id", "run_revision"],
    )
    op.create_check_constraint(
        "ck_flow_run_audit_outbox_target_status",
        "flow_run_audit_outbox",
        f"target_status IN ({_check_values(FLOW_RUN_TERMINAL_STATUSES)})",
    )
    op.create_check_constraint(
        "ck_flow_run_audit_outbox_source",
        "flow_run_audit_outbox",
        f"source IN ({_check_values(OLD_FLOW_RUN_LIFECYCLE_SOURCES)})",
    )
    op.drop_constraint(
        "fk_flow_run_audit_outbox_review_checkpoint",
        "flow_run_audit_outbox",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_flow_run_audit_outbox_review_checkpoint_id",
        table_name="flow_run_audit_outbox",
    )
    op.drop_column("flow_run_audit_outbox", "checkpoint_revision")
    op.drop_column("flow_run_audit_outbox", "review_checkpoint_id")

    op.drop_index(
        "ix_flow_run_review_checkpoints_tenant_created_at",
        table_name="flow_run_review_checkpoints",
    )
    op.drop_index(
        "ix_flow_run_review_checkpoints_run_step_attempt",
        table_name="flow_run_review_checkpoints",
    )
    op.drop_index(
        "uq_flow_run_review_checkpoints_resume_key",
        table_name="flow_run_review_checkpoints",
    )
    op.drop_index(
        "uq_flow_run_review_checkpoints_one_active_per_run",
        table_name="flow_run_review_checkpoints",
    )
    op.drop_index(
        "ix_flow_run_review_checkpoints_tenant_id",
        table_name="flow_run_review_checkpoints",
    )
    op.drop_index(
        "ix_flow_run_review_checkpoints_flow_run_id",
        table_name="flow_run_review_checkpoints",
    )
    op.drop_index(
        "ix_flow_run_review_checkpoints_flow_id",
        table_name="flow_run_review_checkpoints",
    )
    op.drop_table("flow_run_review_checkpoints")

    op.drop_constraint("ck_flow_runs_status", "flow_runs", type_="check")
    op.create_check_constraint(
        "ck_flow_runs_status",
        "flow_runs",
        "status IN ('queued','running','completed','failed','cancelled')",
    )
