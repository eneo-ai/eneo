"""Gallring bookkeeping: job executions, deletion receipts and their manifests.

Owner: eneo.data_retention (job runs, receipts and items are written only through
its repositories). Lifecycle: the flows.housekeeping task prunes final receipts
and finished job runs once they are older than the audit retention window, and
withdrawn receipts (pending ones that released nothing); other unfinished
receipts are never pruned. A receipt is marked when its pruning starts and its
manifest items are deleted in bounded batches before the receipt itself.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from eneo.data_retention.domain.gallring import (
    GALLRING_NAME_PATTERN,
    NON_FINAL_RECEIPT_PHASES,
    GallringCategory,
    GallringEntityKind,
    GallringErrorCode,
    GallringJobOutcome,
    GallringPolicySource,
    GallringTrigger,
    ReceiptItemDisposition,
    ReceiptPhase,
    ReceiptReason,
)
from eneo.database.tables.base_class import BaseWithTableName, IdMixin


def _sql_values(values: Any) -> str:
    return ", ".join(f"'{value.value}'" for value in sorted(values))


_NON_FINAL_PHASES_SQL = f"phase IN ({_sql_values(NON_FINAL_RECEIPT_PHASES)})"
_ACTIVE_PHASES = NON_FINAL_RECEIPT_PHASES - {ReceiptPhase.PAUSED}
# Task names are code identifiers, never content.
_TASK_NAME_SQL = f"task ~ '{GALLRING_NAME_PATTERN}'"


class GallringJobRuns(IdMixin, BaseWithTableName):
    """One execution of one registered task; the running row is the task's lease."""

    task: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=False
    )
    heartbeat_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=False
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))
    batch_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    counts: Mapped[dict[str, int]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    blocked: Mapped[dict[str, int]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    # Each step's durable keyset position ({"at": timestamp, "id": uuid}) by step
    # name; copied into the next execution, removed when the step's pass ends.
    cursors: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    error_code: Mapped[Optional[str]] = mapped_column(sa.String(64))

    __table_args__ = (
        sa.CheckConstraint(
            f"outcome IN ({_sql_values(GallringJobOutcome)})",
            name="ck_gallring_job_runs_outcome",
        ),
        sa.CheckConstraint(
            "(outcome = 'running') = (finished_at IS NULL)",
            name="ck_gallring_job_runs_finished",
        ),
        sa.CheckConstraint(
            f"error_code IS NULL OR error_code IN ({_sql_values(GallringErrorCode)})",
            name="ck_gallring_job_runs_error_code",
        ),
        sa.CheckConstraint(_TASK_NAME_SQL, name="ck_gallring_job_runs_task"),
        sa.CheckConstraint(
            "jsonb_typeof(cursors) = 'object'", name="ck_gallring_job_runs_cursors"
        ),
        # At most one active execution per task: a second claim conflicts here.
        sa.Index(
            "uq_gallring_job_runs_running_task",
            "task",
            unique=True,
            postgresql_where=sa.text("outcome = 'running'"),
        ),
        # A claim reads the step cursors of the task's newest execution.
        sa.Index(
            "ix_gallring_job_runs_task_started_at",
            "task",
            sa.text("started_at DESC"),
        ),
        # Health and status: the latest executions of a task.
        sa.Index(
            "ix_gallring_job_runs_task_finished_at",
            "task",
            sa.text("finished_at DESC"),
        ),
        # Pruning after audit retention.
        sa.Index("ix_gallring_job_runs_finished_at", "finished_at"),
    )


class GallringReceipts(IdMixin, BaseWithTableName):
    """Gallringsbevis for one entity and category, and the resume point of its work."""

    task: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    entity_kind: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    # No foreign key: the receipt outlives the entity it records.
    entity_id: Mapped[UUID] = mapped_column(nullable=False)
    category: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    trigger: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    space_id: Mapped[Optional[UUID]] = mapped_column()
    flow_id: Mapped[Optional[UUID]] = mapped_column()
    policy_source: Mapped[Optional[str]] = mapped_column(sa.String(32))
    policy_days: Mapped[Optional[int]] = mapped_column(sa.Integer)
    anchor_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))
    due_at: Mapped[Optional[datetime]] = mapped_column(sa.TIMESTAMP(timezone=True))
    phase: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    paused_from_phase: Mapped[Optional[str]] = mapped_column(sa.String(16))
    reason: Mapped[Optional[str]] = mapped_column(sa.String(64))
    # Resume point of the manifest enumeration: the last recorded reference.
    manifest_after_file_id: Mapped[Optional[UUID]] = mapped_column()
    manifest_after_variant: Mapped[Optional[str]] = mapped_column(sa.String(32))
    manifest_after_ordinal: Mapped[Optional[int]] = mapped_column(sa.Integer)
    chunk_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    files_deleted: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    started_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=False
    )
    manifest_completed_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True)
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True)
    )
    physical_confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True)
    )
    # Set when pruning starts; the receipt no longer covers its entity.
    pruning_started_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True)
    )

    __table_args__ = (
        sa.CheckConstraint(
            f"phase IN ({_sql_values(ReceiptPhase)})",
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
            f"reason IS NULL OR reason IN ({_sql_values(ReceiptReason)})",
            name="ck_gallring_receipts_reason",
        ),
        sa.CheckConstraint(
            "paused_from_phase IS NULL OR paused_from_phase IN "
            f"({_sql_values(_ACTIVE_PHASES)})",
            name="ck_gallring_receipts_paused_from_value",
        ),
        sa.CheckConstraint(
            f"entity_kind IN ({_sql_values(GallringEntityKind)})",
            name="ck_gallring_receipts_entity_kind",
        ),
        sa.CheckConstraint(
            f"category IN ({_sql_values(GallringCategory)})",
            name="ck_gallring_receipts_category",
        ),
        sa.CheckConstraint(
            "policy_source IS NULL OR policy_source IN "
            f"({_sql_values(GallringPolicySource)})",
            name="ck_gallring_receipts_policy_source",
        ),
        sa.CheckConstraint("files_deleted >= 0", name="ck_gallring_receipts_files"),
        sa.CheckConstraint(
            "(manifest_after_file_id IS NULL) = (manifest_after_variant IS NULL) "
            "AND (manifest_after_file_id IS NULL) = (manifest_after_ordinal IS NULL)",
            name="ck_gallring_receipts_manifest_after",
        ),
        sa.CheckConstraint(
            f"manifest_after_variant ~ '{GALLRING_NAME_PATTERN}' "
            "AND manifest_after_ordinal >= 0",
            name="ck_gallring_receipts_manifest_after_value",
        ),
        sa.CheckConstraint(_TASK_NAME_SQL, name="ck_gallring_receipts_task"),
        sa.CheckConstraint(
            f"trigger IN ({_sql_values(GallringTrigger)})",
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
        sa.CheckConstraint(
            "pruning_started_at IS NULL OR phase IN ('completed', 'pending', 'stopped')",
            name="ck_gallring_receipts_pruning",
        ),
        # One receipt per entity and category that is not being pruned; discovery
        # skips recorded entities.
        sa.Index(
            "uq_gallring_receipts_entity_category",
            "task",
            "entity_kind",
            "entity_id",
            "category",
            unique=True,
            postgresql_where=sa.text("pruning_started_at IS NULL"),
        ),
        # Pruning continues the receipts it marked, oldest first.
        sa.Index(
            "ix_gallring_receipts_pruning",
            "pruning_started_at",
            "id",
            postgresql_where=sa.text("pruning_started_at IS NOT NULL"),
        ),
        # Resume: the unfinished receipts of a task, oldest first.
        sa.Index(
            "ix_gallring_receipts_unfinished",
            "task",
            "started_at",
            "id",
            postgresql_where=sa.text(_NON_FINAL_PHASES_SQL),
        ),
        # Physical tracking: completed receipts whose bytes are not confirmed gone.
        sa.Index(
            "ix_gallring_receipts_physical_pending",
            "completed_at",
            "id",
            postgresql_where=sa.text(
                "phase = 'completed' AND physical_confirmed_at IS NULL"
            ),
        ),
        # Pruning after audit retention.
        sa.Index("ix_gallring_receipts_completed_at", "completed_at"),
    )


class GallringReceiptItems(BaseWithTableName):
    """Complete manifest: every (file, content) pair a receipt releases."""

    id: Mapped[int] = mapped_column(sa.BigInteger, sa.Identity(), primary_key=True)
    receipt_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("gallring_receipts.id", ondelete="CASCADE"), nullable=False
    )
    file_id: Mapped[UUID] = mapped_column(nullable=False)
    content_id: Mapped[UUID] = mapped_column(nullable=False)
    disposition: Mapped[Optional[str]] = mapped_column(sa.String(16))
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True)
    )

    __table_args__ = (
        sa.CheckConstraint(
            f"disposition IS NULL OR disposition IN "
            f"({_sql_values(ReceiptItemDisposition)})",
            name="ck_gallring_receipt_items_disposition",
        ),
        sa.CheckConstraint(
            "(disposition IS NULL) = (confirmed_at IS NULL)",
            name="ck_gallring_receipt_items_confirmed",
        ),
        # Manifest traversal per receipt (keyset) and the receipt FK cascade.
        sa.Index("ix_gallring_receipt_items_receipt_id_id", "receipt_id", "id"),
        # Physical tracking: the unconfirmed items of a receipt.
        sa.Index(
            "ix_gallring_receipt_items_unconfirmed",
            "receipt_id",
            postgresql_where=sa.text("confirmed_at IS NULL"),
        ),
    )
