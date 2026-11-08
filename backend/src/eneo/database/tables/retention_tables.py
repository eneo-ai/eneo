"""Persisted retention executions: leases, durable discovery cursors and progress."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Optional

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from eneo.data_retention.domain.retention import (
    RETENTION_NAME_PATTERN,
    RetentionErrorCode,
    RetentionJobOutcome,
)
from eneo.database.tables.base_class import BaseWithTableName, IdMixin


def _sql_values(values: Iterable[StrEnum]) -> str:
    return ", ".join(f"'{value.value}'" for value in sorted(values))


_TASK_NAME_SQL = f"task ~ '{RETENTION_NAME_PATTERN}'"


class RetentionJobRuns(IdMixin, BaseWithTableName):
    """One execution of one registered task; the running row is the task's lease."""

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return "retention_job_runs"

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
    cursors: Mapped[dict[str, JsonValue]] = mapped_column(
        JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
    )
    error_code: Mapped[Optional[str]] = mapped_column(sa.String(64))
    # The task's overdue snapshot, written when the execution ends (every
    # outcome); all four are set together or none.
    overdue_observed_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True)
    )
    overdue_count: Mapped[Optional[int]] = mapped_column(sa.Integer)
    overdue_complete: Mapped[Optional[bool]] = mapped_column(sa.Boolean)
    overdue_oldest_due_at: Mapped[Optional[datetime]] = mapped_column(
        sa.TIMESTAMP(timezone=True)
    )

    __table_args__ = (
        sa.CheckConstraint(
            f"outcome IN ({_sql_values(RetentionJobOutcome)})",
            name="ck_retention_job_runs_outcome",
        ),
        sa.CheckConstraint(
            "(outcome = 'running') = (finished_at IS NULL)",
            name="ck_retention_job_runs_finished",
        ),
        sa.CheckConstraint(
            f"error_code IS NULL OR error_code IN ({_sql_values(RetentionErrorCode)})",
            name="ck_retention_job_runs_error_code",
        ),
        sa.CheckConstraint(_TASK_NAME_SQL, name="ck_retention_job_runs_task"),
        sa.CheckConstraint(
            "jsonb_typeof(cursors) = 'object'", name="ck_retention_job_runs_cursors"
        ),
        sa.CheckConstraint(
            "(overdue_observed_at IS NULL) = (overdue_count IS NULL) "
            "AND (overdue_observed_at IS NULL) = (overdue_complete IS NULL) "
            "AND (overdue_count IS NULL OR overdue_count >= 0) "
            "AND COALESCE(overdue_count > 0, false) = "
            "(overdue_oldest_due_at IS NOT NULL)",
            name="ck_retention_job_runs_overdue",
        ),
        # At most one active execution per task: a second claim conflicts here.
        sa.Index(
            "uq_retention_job_runs_running_task",
            "task",
            unique=True,
            postgresql_where=sa.text("outcome = 'running'"),
        ),
        # A claim reads the step cursors of the task's newest execution.
        sa.Index(
            "ix_retention_job_runs_task_started_at",
            "task",
            sa.text("started_at DESC"),
            sa.text("id DESC"),
        ),
        # Health and status: the latest executions of a task.
        sa.Index(
            "ix_retention_job_runs_task_finished_at",
            "task",
            sa.text("finished_at DESC"),
        ),
        # Health reads the latest persisted overdue snapshot independently of outcome.
        sa.Index(
            "ix_retention_job_runs_task_overdue_observed_at",
            "task",
            sa.text("overdue_observed_at DESC"),
            postgresql_where=sa.text("overdue_observed_at IS NOT NULL"),
        ),
        # Pruning after audit retention.
        sa.Index("ix_retention_job_runs_finished_at", "finished_at"),
    )
