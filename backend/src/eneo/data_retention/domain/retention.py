"""Retention execution value types: budgets, job outcomes and discovery positions.

Pure domain code: no I/O. The application layer persists these states; the
database CHECK constraints mirror the closed sets defined here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid5

# Every registered task runs once a day; health compares against this cadence.
RETENTION_CADENCE = timedelta(days=1)
# A task without a completed execution for this long is stale.
RETENTION_STALE_AFTER = 2 * RETENTION_CADENCE

# Namespace for deterministic audit ids (uuid5 over the batch or execution).
_RETENTION_AUDIT_NAMESPACE = UUID("6f1d3a0e-7c55-4a8e-9a43-0b7f3a6c2d11")


class RetentionJobOutcome(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    # The budget ran out with work left; the next execution resumes it.
    PARTIAL = "partial"
    FAILED = "failed"
    # A later execution took the task over after this one's heartbeat went stale.
    SUPERSEDED = "superseded"
    # The run did not start: the deployment's emergency switch suppressed it
    # (also audited) or its claim timed out waiting on another execution's lock.
    SKIPPED = "skipped"


# Outcomes of an execution that ran to its own end (health: the task is alive).
RETENTION_COMPLETED_OUTCOMES = frozenset(
    {RetentionJobOutcome.SUCCEEDED, RetentionJobOutcome.PARTIAL}
)


# Task, step and count names are code identifiers, never content.
RETENTION_NAME_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"
_NAME = re.compile(RETENTION_NAME_PATTERN)


def retention_name(value: str) -> str:
    if len(value) > 64 or not _NAME.fullmatch(value):
        raise ValueError("A retention task, step or count name is a code identifier.")
    return value


class RetentionErrorCode(StrEnum):
    # A chunk waited past its statement or lock timeout; the run is partial.
    CHUNK_TIMEOUT = "chunk_timeout"
    # PostgreSQL ended a lock cycle with another transaction by aborting the
    # chunk; the run is partial and the next execution retries.
    CHUNK_DEADLOCK = "chunk_deadlock"
    CHUNK_FAILED = "chunk_failed"
    # A task broke the adopter contract (a name outside its closed sets, an
    # over-charge): a code defect, not a database failure.
    CONTRACT_VIOLATION = "contract_violation"
    CLAIM_TIMEOUT = "claim_timeout"
    # The final outcome could not be written; the stale takeover records the row.
    FINISH_TIMEOUT = "finish_timeout"
    DISABLED_BY_DEPLOYMENT_SETTING = "disabled_by_deployment_setting"


@dataclass(frozen=True, slots=True)
class RetentionUsage:
    rows: int = 0
    files: int = 0

    def plus(self, *, rows: int, files: int) -> RetentionUsage:
        return RetentionUsage(rows=self.rows + rows, files=self.files + files)


@dataclass(frozen=True, slots=True)
class RetentionOverdue:
    """A task's count of due work still stored past its deadline and window.

    `count` is capped; `complete` says whether the cap covered all of it.
    """

    count: int
    complete: bool
    oldest_due_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValueError("An overdue count is not negative.")
        if (self.count == 0) != (self.oldest_due_at is None):
            raise ValueError("Only overdue work has an oldest deadline.")


@dataclass(frozen=True, slots=True)
class RetentionBudget:
    """What one execution of one task may spend: rows, files and seconds."""

    rows: int
    files: int
    seconds: float

    def __post_init__(self) -> None:
        if self.rows <= 0 or self.files <= 0 or self.seconds <= 0:
            raise ValueError("A retention budget must be positive.")

    def left(self, used: RetentionUsage, *, elapsed_seconds: float) -> RetentionUsage:
        """Rows and files still available; zero in both once any limit is spent."""
        if elapsed_seconds >= self.seconds:
            return RetentionUsage()
        rows = self.rows - used.rows
        files = self.files - used.files
        if rows <= 0 or files <= 0:
            return RetentionUsage()
        return RetentionUsage(rows=rows, files=files)


@dataclass(frozen=True, slots=True)
class RetentionKeyset:
    """A step's durable discovery position: a keyset of a timestamp and an id.

    Ids and timestamps only (proof without content); the job run keeps one per
    step so the next execution continues the pass where this one stopped.
    """

    at: datetime
    id: UUID
    # A step that pages within owners names the current owner group.
    group: UUID | None = None

    def __post_init__(self) -> None:
        _validate_keyset(self.at, self.id, self.group)


def _validate_keyset(at: object, identifier: object, group: object) -> None:
    """Persisted cursor inputs must meet the value contract at runtime as well."""
    if not isinstance(at, datetime) or at.tzinfo is None:
        raise TypeError("A keyset position is an aware timestamp.")
    if not isinstance(identifier, UUID):
        raise TypeError("A keyset position ends with an id.")
    if group is not None and not isinstance(group, UUID):
        raise TypeError("A keyset group is an id.")


def _words(key: str) -> str:
    return key.replace(".", " ").replace("_", " ")


def retention_summary(counts: Mapping[str, int], blocked: Mapping[str, int]) -> str:
    """An administrator's reading of audited counts, for example "questions
    deleted 12, sessions deleted 3, by space rule 12; kept 1 root locked,
    2 files locked".

    Built only from the task's closed key names, never from content. Every
    count reads as "<key words> <n>" and every kept reason as "<n> <reason
    words>", so no number is put before a noun it might not agree with; a
    run's `<step>.<reason>` key reads as "<step> <reason words>".
    """
    done = [f"{_words(key)} {value}" for key, value in counts.items() if value]
    kept = [f"{value} {_words(reason)}" for reason, value in blocked.items() if value]
    parts = [
        *([", ".join(done)] if done else []),
        *(["kept " + ", ".join(kept)] if kept else []),
    ]
    return "; ".join(parts) if parts else "nothing deleted"


def retention_run_audit_id(job_run_id: UUID) -> UUID:
    """The one end-of-execution audit id: a second event for the same execution
    conflicts with the first."""
    return uuid5(_RETENTION_AUDIT_NAMESPACE, f"{job_run_id}:run")


def retention_batch_audit_id(
    *, job_run_id: UUID, batch_seq: int, tenant_id: UUID
) -> UUID:
    """One audit id per batch and tenant: a second event for the same batch and
    tenant conflicts with the first instead of adding to the trail."""
    return uuid5(_RETENTION_AUDIT_NAMESPACE, f"{job_run_id}:{batch_seq}:{tenant_id}")
