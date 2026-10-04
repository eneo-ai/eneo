"""Gallring (scheduled deletion) value types: budgets, job outcomes, receipt phases.

Pure domain code: no I/O. The application layer persists these states; the
database CHECK constraints mirror the closed sets defined here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid5

# Every registered task runs once a day; health compares against this cadence.
GALLRING_CADENCE = timedelta(days=1)

# Namespace for deterministic batch audit ids (uuid5 over the batch identity).
_GALLRING_AUDIT_NAMESPACE = UUID("6f1d3a0e-7c55-4a8e-9a43-0b7f3a6c2d11")


class GallringJobOutcome(StrEnum):
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
GALLRING_COMPLETED_OUTCOMES = frozenset(
    {GallringJobOutcome.SUCCEEDED, GallringJobOutcome.PARTIAL}
)


# Task, step and count names are code identifiers, never content.
GALLRING_NAME_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"
_NAME = re.compile(GALLRING_NAME_PATTERN)


def gallring_name(value: str) -> str:
    if len(value) > 64 or not _NAME.fullmatch(value):
        raise ValueError("A gallring task, step or count name is a code identifier.")
    return value


class GallringErrorCode(StrEnum):
    CHUNK_TIMEOUT = "chunk_timeout"
    CHUNK_FAILED = "chunk_failed"
    CLAIM_TIMEOUT = "claim_timeout"
    # The final outcome could not be written; the stale takeover records the row.
    FINISH_TIMEOUT = "finish_timeout"
    DISABLED_BY_DEPLOYMENT_SETTING = "disabled_by_deployment_setting"


@dataclass(frozen=True, slots=True)
class GallringUsage:
    rows: int = 0
    files: int = 0

    def plus(self, *, rows: int, files: int) -> GallringUsage:
        return GallringUsage(rows=self.rows + rows, files=self.files + files)


@dataclass(frozen=True, slots=True)
class GallringBudget:
    """What one execution of one task may spend: rows, files and seconds."""

    rows: int
    files: int
    seconds: float

    def __post_init__(self) -> None:
        if self.rows <= 0 or self.files <= 0 or self.seconds <= 0:
            raise ValueError("A gallring budget must be positive.")

    def left(self, used: GallringUsage, *, elapsed_seconds: float) -> GallringUsage:
        """Rows and files still available; zero in both once any limit is spent."""
        if elapsed_seconds >= self.seconds:
            return GallringUsage()
        rows = self.rows - used.rows
        files = self.files - used.files
        if rows <= 0 or files <= 0:
            return GallringUsage()
        return GallringUsage(rows=rows, files=files)


class ReceiptPhase(StrEnum):
    # Created; the manifest is being enumerated and nothing is released yet.
    PENDING = "pending"
    # The manifest is complete and the discovery anchor has been released.
    RELEASING = "releasing"
    DELETING = "deleting"
    COMPLETED = "completed"
    # Unfinished work waiting on a blocker; never final, never pruned.
    PAUSED = "paused"
    STOPPED = "stopped"


FINAL_RECEIPT_PHASES = frozenset({ReceiptPhase.COMPLETED, ReceiptPhase.STOPPED})
NON_FINAL_RECEIPT_PHASES = frozenset(ReceiptPhase) - FINAL_RECEIPT_PHASES

_FORWARD: dict[ReceiptPhase, frozenset[ReceiptPhase]] = {
    ReceiptPhase.PENDING: frozenset({ReceiptPhase.RELEASING}),
    ReceiptPhase.RELEASING: frozenset({ReceiptPhase.DELETING}),
    ReceiptPhase.DELETING: frozenset({ReceiptPhase.COMPLETED}),
}


class ReceiptReason(StrEnum):
    """Why a receipt is paused or stopped."""

    FILE_REFERENCED_ELSEWHERE = "file_referenced_elsewhere"
    DERIVED_FILE_REFERENCED_ELSEWHERE = "derived_file_referenced_elsewhere"
    # The family nests deeper than its traversal reaches; nothing is released.
    FAMILY_DEPTH_EXCEEDED = "family_depth_exceeded"
    # The family needs more rows than one execution may spend on a family.
    FAMILY_EXCEEDS_BUDGET = "family_exceeds_budget"


class InvalidReceiptTransition(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReceiptState:
    phase: ReceiptPhase
    paused_from: ReceiptPhase | None = None
    reason: ReceiptReason | None = None

    def __post_init__(self) -> None:
        paused = self.phase == ReceiptPhase.PAUSED
        if paused != (self.paused_from is not None):
            raise InvalidReceiptTransition("Only a paused receipt has a resume phase.")
        if self.paused_from in FINAL_RECEIPT_PHASES or (
            self.paused_from == ReceiptPhase.PAUSED
        ):
            raise InvalidReceiptTransition("A receipt resumes to an active phase.")
        if (self.reason is not None) != (
            self.phase in {ReceiptPhase.PAUSED, ReceiptPhase.STOPPED}
        ):
            raise InvalidReceiptTransition("Paused and stopped receipts need a reason.")

    @property
    def is_final(self) -> bool:
        return self.phase in FINAL_RECEIPT_PHASES

    def advance(self, target: ReceiptPhase) -> ReceiptState:
        if target not in _FORWARD.get(self.phase, frozenset()):
            raise InvalidReceiptTransition(
                f"A receipt cannot move from {self.phase} to {target}."
            )
        return ReceiptState(phase=target)

    def pause(self, reason: ReceiptReason) -> ReceiptState:
        if self.is_final or self.phase == ReceiptPhase.PAUSED:
            raise InvalidReceiptTransition(f"A {self.phase} receipt cannot pause.")
        return ReceiptState(
            phase=ReceiptPhase.PAUSED, paused_from=self.phase, reason=reason
        )

    def resume(self) -> ReceiptState:
        if self.paused_from is None:
            raise InvalidReceiptTransition(f"A {self.phase} receipt cannot resume.")
        return ReceiptState(phase=self.paused_from)

    def stop(self, reason: ReceiptReason) -> ReceiptState:
        if self.is_final:
            raise InvalidReceiptTransition(f"A {self.phase} receipt cannot stop.")
        return ReceiptState(phase=ReceiptPhase.STOPPED, reason=reason)


class GallringEntityKind(StrEnum):
    # A root file and every file derived from it (files.parent_file_id).
    FILE_FAMILY = "file_family"


class GallringCategory(StrEnum):
    ABANDONED_UPLOAD = "abandoned_upload"
    TEMPLATE_ASSET = "template_asset"


class GallringPolicySource(StrEnum):
    TENANT = "tenant"
    DEFAULT = "default"


class GallringTrigger(StrEnum):
    SCHEDULED = "scheduled"
    EXPLICIT = "explicit"


@dataclass(frozen=True, slots=True)
class NewGallringReceipt:
    task: str
    entity_kind: GallringEntityKind
    entity_id: UUID
    category: GallringCategory
    tenant_id: UUID
    flow_id: UUID | None = None
    space_id: UUID | None = None
    policy_source: GallringPolicySource | None = None
    policy_days: int | None = None
    anchor_at: datetime | None = None
    due_at: datetime | None = None
    trigger: GallringTrigger = GallringTrigger.SCHEDULED

    def __post_init__(self) -> None:
        gallring_name(self.task)


@dataclass(frozen=True, slots=True)
class ManifestPosition:
    """Where a manifest enumeration resumes: a file and one content reference.

    Ids and codes only: the reference's variant code and ordinal.
    """

    file_id: UUID
    variant: str
    ordinal: int

    def __post_init__(self) -> None:
        if not isinstance(cast(object, self.file_id), UUID):
            raise TypeError("A manifest position names a file by its id.")
        gallring_name(self.variant)
        if self.ordinal < 0:
            raise ValueError("A content reference ordinal is not negative.")


@dataclass(frozen=True, slots=True)
class GallringReceipt:
    id: UUID
    entity_id: UUID
    tenant_id: UUID
    flow_id: UUID | None
    category: GallringCategory
    state: ReceiptState
    # Resume point of the manifest enumeration: the last recorded reference.
    manifest_after: ManifestPosition | None
    files_deleted: int
    manifest_complete: bool
    started_at: datetime


@dataclass(frozen=True, slots=True)
class ReceiptUpdate:
    state: ReceiptState
    manifest_after: ManifestPosition | None = None
    files_deleted: int = 0
    manifest_complete: bool = False

    def __post_init__(self) -> None:
        # The resume point is typed; a name or any other value is refused.
        if self.manifest_after is not None and not isinstance(
            cast(object, self.manifest_after), ManifestPosition
        ):
            raise TypeError("A receipt's resume point is a manifest position.")
        if self.files_deleted < 0:
            raise ValueError("A receipt cannot count negative deletions.")


@dataclass(frozen=True, slots=True)
class PhysicalReceiptKey:
    completed_at: datetime
    id: UUID
    tenant_id: UUID


@dataclass(frozen=True, slots=True)
class PhysicalItemPage:
    examined: int
    last_item: int | None
    # No unconfirmed item follows this page.
    finished: bool


@dataclass(frozen=True, slots=True)
class PrunedReceipts:
    """What one bounded pruning call wrote, per tenant; `rows` is their sum."""

    rows: int
    # Receipts deleted, with their tenant.
    receipts: tuple[tuple[UUID, UUID], ...] = ()
    # Manifest items deleted, per tenant of their receipt.
    items_deleted: Mapping[UUID, int] = field(default_factory=dict[UUID, int])
    # Receipts marked for pruning, per tenant.
    receipts_marked: Mapping[UUID, int] = field(default_factory=dict[UUID, int])


@dataclass(frozen=True, slots=True)
class GallringKeyset:
    """A step's durable discovery position: a keyset of a timestamp and an id,
    and optionally a position (a row number) inside that row's own items.

    Ids, timestamps and numbers only (proof without content); the job run keeps
    one per step so the next execution continues the pass where this one
    stopped.
    """

    at: datetime
    id: UUID
    item: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(cast(object, self.at), datetime) or self.at.tzinfo is None:
            raise TypeError("A keyset position is an aware timestamp.")
        if not isinstance(cast(object, self.id), UUID):
            raise TypeError("A keyset position ends with an id.")
        item = cast(object, self.item)
        if item is not None and (
            not isinstance(item, int) or isinstance(item, bool) or item < 0
        ):
            raise TypeError("An item position is a non-negative number.")


@dataclass(frozen=True, slots=True)
class PhysicalCursor:
    """Where physical confirmation continues: a receipt and an item within it.

    With an item position (0 for its first item) the receipt is examined from
    there; without one, confirmation continues after the receipt.
    """

    receipt: GallringKeyset
    after_item: int | None = None


class ReceiptItemDisposition(StrEnum):
    """What the content owner reports for one manifest item."""

    # The content row is gone or tombstoned: the bytes are deleted.
    DELETED = "deleted"
    # Another reference keeps the content; no physical deletion is due.
    SHARED = "shared"


def gallring_batch_audit_id(
    *, job_run_id: UUID, batch_seq: int, tenant_id: UUID
) -> UUID:
    """One audit id per committed batch and tenant; replaying a batch reuses it."""
    return uuid5(_GALLRING_AUDIT_NAMESPACE, f"{job_run_id}:{batch_seq}:{tenant_id}")
