"""add the gallring job runs, receipts and receipt items

Revision ID: 202610041200
Revises: 202610041000
Create Date: 2026-10-04 12:00:00.000000

New, empty tables only: plain transactional DDL, so a failed upgrade leaves
nothing behind and re-runs; it also runs offline.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202610041200"
down_revision: str = "202610041000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NON_FINAL_PHASES = "phase IN ('deleting', 'paused', 'pending', 'releasing')"
_TASK_NAME = "task ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$'"


def upgrade() -> None:
    op.create_table(
        "gallring_job_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("task", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "batch_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "counts",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "blocked",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "cursors",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "outcome IN ('failed', 'partial', 'running', 'skipped', 'succeeded', "
            "'superseded')",
            name="ck_gallring_job_runs_outcome",
        ),
        sa.CheckConstraint(
            "(outcome = 'running') = (finished_at IS NULL)",
            name="ck_gallring_job_runs_finished",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN ('chunk_failed', 'chunk_timeout', "
            "'claim_timeout', 'disabled_by_deployment_setting', 'finish_timeout')",
            name="ck_gallring_job_runs_error_code",
        ),
        sa.CheckConstraint(_TASK_NAME, name="ck_gallring_job_runs_task"),
        sa.CheckConstraint(
            "jsonb_typeof(cursors) = 'object'", name="ck_gallring_job_runs_cursors"
        ),
    )
    op.create_index(
        "uq_gallring_job_runs_running_task",
        "gallring_job_runs",
        ["task"],
        unique=True,
        postgresql_where=sa.text("outcome = 'running'"),
    )
    op.create_index(
        "ix_gallring_job_runs_task_started_at",
        "gallring_job_runs",
        ["task", sa.text("started_at DESC")],
    )
    op.create_index(
        "ix_gallring_job_runs_task_finished_at",
        "gallring_job_runs",
        ["task", sa.text("finished_at DESC")],
    )
    op.create_index(
        "ix_gallring_job_runs_finished_at", "gallring_job_runs", ["finished_at"]
    )

    op.create_table(
        "gallring_receipts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("task", sa.String(64), nullable=False),
        sa.Column("entity_kind", sa.String(32), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("policy_source", sa.String(32), nullable=True),
        sa.Column("policy_days", sa.Integer(), nullable=True),
        sa.Column("anchor_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("due_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("paused_from_phase", sa.String(16), nullable=True),
        sa.Column("reason", sa.String(64), nullable=True),
        sa.Column(
            "manifest_after_file_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("manifest_after_variant", sa.String(32), nullable=True),
        sa.Column("manifest_after_ordinal", sa.Integer(), nullable=True),
        sa.Column(
            "chunk_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "files_deleted", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("manifest_completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("physical_confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("pruning_started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "pruning_started_at IS NULL OR phase IN ('completed', 'pending', 'stopped')",
            name="ck_gallring_receipts_pruning",
        ),
        sa.CheckConstraint(
            "phase IN ('completed', 'deleting', 'paused', 'pending', 'releasing', "
            "'stopped')",
            name="ck_gallring_receipts_phase",
        ),
        sa.CheckConstraint(
            "(phase = 'paused') = (paused_from_phase IS NOT NULL)",
            name="ck_gallring_receipts_paused_from",
        ),
        sa.CheckConstraint(
            "(phase IN ('paused', 'stopped')) = (reason IS NOT NULL)",
            name="ck_gallring_receipts_reason_present",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN ('derived_file_referenced_elsewhere', "
            "'family_depth_exceeded', 'family_exceeds_budget', "
            "'file_referenced_elsewhere')",
            name="ck_gallring_receipts_reason",
        ),
        sa.CheckConstraint(
            "paused_from_phase IS NULL OR paused_from_phase IN ('deleting', "
            "'pending', 'releasing')",
            name="ck_gallring_receipts_paused_from_value",
        ),
        sa.CheckConstraint(
            "entity_kind IN ('file_family')",
            name="ck_gallring_receipts_entity_kind",
        ),
        sa.CheckConstraint(
            "category IN ('abandoned_upload', 'template_asset')",
            name="ck_gallring_receipts_category",
        ),
        sa.CheckConstraint(
            "policy_source IS NULL OR policy_source IN ('default', 'tenant')",
            name="ck_gallring_receipts_policy_source",
        ),
        sa.CheckConstraint("files_deleted >= 0", name="ck_gallring_receipts_files"),
        sa.CheckConstraint(
            "(manifest_after_file_id IS NULL) = (manifest_after_variant IS NULL) "
            "AND (manifest_after_file_id IS NULL) = (manifest_after_ordinal IS NULL)",
            name="ck_gallring_receipts_manifest_after",
        ),
        sa.CheckConstraint(
            "manifest_after_variant ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$' "
            "AND manifest_after_ordinal >= 0",
            name="ck_gallring_receipts_manifest_after_value",
        ),
        sa.CheckConstraint(_TASK_NAME, name="ck_gallring_receipts_task"),
        sa.CheckConstraint(
            "trigger IN ('explicit', 'scheduled')",
            name="ck_gallring_receipts_trigger",
        ),
        sa.CheckConstraint(
            "phase <> 'completed' OR manifest_completed_at IS NOT NULL",
            name="ck_gallring_receipts_completed",
        ),
        sa.CheckConstraint(
            "(phase IN ('completed', 'stopped')) = (completed_at IS NOT NULL)",
            name="ck_gallring_receipts_finished",
        ),
        sa.CheckConstraint(
            "physical_confirmed_at IS NULL OR phase = 'completed'",
            name="ck_gallring_receipts_physical_confirmed",
        ),
    )
    op.create_index(
        "uq_gallring_receipts_entity_category",
        "gallring_receipts",
        ["task", "entity_kind", "entity_id", "category"],
        unique=True,
        postgresql_where=sa.text("pruning_started_at IS NULL"),
    )
    op.create_index(
        "ix_gallring_receipts_pruning",
        "gallring_receipts",
        ["pruning_started_at", "id"],
        postgresql_where=sa.text("pruning_started_at IS NOT NULL"),
    )
    op.create_index(
        "ix_gallring_receipts_unfinished",
        "gallring_receipts",
        ["task", "started_at", "id"],
        postgresql_where=sa.text(_NON_FINAL_PHASES),
    )
    op.create_index(
        "ix_gallring_receipts_physical_pending",
        "gallring_receipts",
        ["completed_at", "id"],
        postgresql_where=sa.text(
            "phase = 'completed' AND physical_confirmed_at IS NULL"
        ),
    )
    op.create_index(
        "ix_gallring_receipts_completed_at", "gallring_receipts", ["completed_at"]
    )

    op.create_table(
        "gallring_receipt_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("disposition", sa.String(16), nullable=True),
        sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["gallring_receipts.id"],
            name="gallring_receipt_items_receipt_id_fkey",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "disposition IS NULL OR disposition IN ('deleted', 'shared')",
            name="ck_gallring_receipt_items_disposition",
        ),
        sa.CheckConstraint(
            "(disposition IS NULL) = (confirmed_at IS NULL)",
            name="ck_gallring_receipt_items_confirmed",
        ),
    )
    op.create_index(
        "ix_gallring_receipt_items_receipt_id_id",
        "gallring_receipt_items",
        ["receipt_id", "id"],
    )
    op.create_index(
        "ix_gallring_receipt_items_unconfirmed",
        "gallring_receipt_items",
        ["receipt_id"],
        postgresql_where=sa.text("confirmed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("gallring_receipt_items")
    op.drop_table("gallring_receipts")
    op.drop_table("gallring_job_runs")
