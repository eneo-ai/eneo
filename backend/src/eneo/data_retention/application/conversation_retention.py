"""One bounded conversation page; the retention runner owns its transaction."""

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from eneo.data_retention.application.retention_runner import (
    RetentionBatch,
    RetentionStepResult,
)
from eneo.data_retention.application.retention_units import (
    RetentionEffects,
    retention_unit_allowance,
)
from eneo.data_retention.constants import (
    CONVERSATION_UNIT_OVERHEAD_ROWS,
    validate_conversation_unit_budget,
)
from eneo.data_retention.domain.retention import (
    RetentionKeyset,
)
from eneo.files.file_retention import FileRetentionReason
from eneo.policy_levels import PolicyLevel


class ConversationRootKind(StrEnum):
    QUESTION = "question"
    APP_RUN = "app_run"

    @property
    def deleted_key(self) -> str:
        """The count of deleted roots, named for what a root is in the product."""
        return (
            "questions_deleted"
            if self is ConversationRootKind.QUESTION
            else "app_runs_deleted"
        )


class ConversationBlockReason(StrEnum):
    UNIT_EXCEEDS_BUDGET = "unit_exceeds_budget"
    NO_LONGER_DUE = "no_longer_due"
    # Another transaction held a row the unit locks first without waiting:
    # the root, or a question's session.
    ROOT_LOCKED = "root_locked"
    # Another transaction held a row the root DELETE cascades to (a child row
    # or stored content), past the lock timeout.
    CASCADE_LOCKED = "cascade_locked"

    @property
    def key(self) -> str:
        """The blocked count name, as FileRetentionReason.key is for a File."""
        return self.value


# File refusals that keep the conversation: its unit rolls back whole and is
# blocked under the File's own key. A budget shortage is the unit's, not the
# File's: it is retried fresh or blocked as unit_exceeds_budget.
CONVERSATION_FILE_BLOCKS = frozenset(
    reason
    for reason in FileRetentionReason
    if reason.rolls_back and reason is not FileRetentionReason.INSUFFICIENT_BUDGET
)

# A conversation is kept for its own reason or for a File refusal.
ConversationUnitBlock = ConversationBlockReason | FileRetentionReason


@dataclass(frozen=True, slots=True)
class ConversationDeletion:
    id: UUID
    tenant_id: UUID
    # The level whose period removed it; None when no period did (a copy of a
    # removed conversation).
    source: PolicyLevel | None


@dataclass(frozen=True, slots=True)
class ConversationUnitResult:
    rows: int
    files: int
    deletion: ConversationDeletion | None = None
    sessions_deleted: int = 0
    files_deleted: int = 0
    # Files of a deleted conversation that its release kept, by reason.
    file_outcomes: Mapping[FileRetentionReason, int] = field(
        default_factory=dict[FileRetentionReason, int]
    )
    block: ConversationUnitBlock | None = None
    fits: bool = True


# The keyset after every root of its owner (the keyset group): an owner whose
# due roots were all visited, so the next page starts at the following owner.
_PAST_OWNER_AT = datetime.max.replace(tzinfo=timezone.utc)
_PAST_OWNER_ID = UUID(int=(1 << 128) - 1)


def past_owner(owner: UUID) -> RetentionKeyset:
    return RetentionKeyset(at=_PAST_OWNER_AT, id=_PAST_OWNER_ID, group=owner)


def is_past_owner(cursor: RetentionKeyset) -> bool:
    return cursor.at == _PAST_OWNER_AT and cursor.id == _PAST_OWNER_ID


@dataclass(frozen=True, slots=True)
class ConversationPage:
    """Selected roots of one discovery page, in keyset order.

    `examined` discovery rows (owners or edges, at most the page limit) were
    read after the cursor, and the roots they select up to the same limit.
    `done` is the cursor once every root is visited, None when discovery found
    nothing; `complete` says the discovery window reached the end of its keys.
    `passed_ids` are roots another task owns (a widget conversation's
    questions): read and charged with the page, never locked or deleted.
    """

    roots: Sequence[RetentionKeyset]
    locked_ids: Sequence[UUID]
    examined: int
    done: RetentionKeyset | None
    complete: bool
    passed_ids: Sequence[UUID] = ()


class ConversationPageRepository(Protocol):
    @property
    def kind(self) -> ConversationRootKind: ...

    @property
    def examined_key(self) -> str:
        """The observation count of the discovery rows a page examined."""
        ...

    async def lock_due_page(
        self, cursor: RetentionKeyset | None, limit: int
    ) -> ConversationPage:
        """At most `limit` discovery rows after `cursor`, then at most `limit`
        of the roots they select after it, locked."""
        ...

    async def cascade_cost(self, identifier: UUID, ceiling: int) -> int | None:
        """Rows one root's removal writes, counting at most `ceiling + 1` in
        total, or None when another transaction holds the root's session."""
        ...

    async def delete_unit(
        self,
        identifier: UUID,
        *,
        child_rows: int,
        max_rows: int,
        max_files: int,
        max_family_rows: int,
    ) -> ConversationUnitResult: ...


@dataclass(slots=True)
class ConversationRootCostEstimate:
    """Rows a step's latest chunk charged per visited root, kept for one execution.

    Every locked root is charged its discovery, and a root the chunk cannot
    reach is locked and charged again by the next chunk, so the page follows
    what roots recently cost instead of assuming they are all cheap.
    """

    unit_rows: int = CONVERSATION_UNIT_OVERHEAD_ROWS


@dataclass(frozen=True, slots=True)
class ConversationPageAllocation:
    unit_rows: int
    unit_files: int
    chunk_rows: int
    # The most owners (and roots) one discovery page reads, from a full chunk.
    page_size: int
    max_batch: int
    family_rows: int


def conversation_page_allocation(
    *,
    unit_rows: int,
    chunk_rows: int,
    execution_rows: int,
    execution_files: int,
    family_rows: int,
) -> ConversationPageAllocation:
    validate_conversation_unit_budget(
        unit_rows=unit_rows, execution_rows=execution_rows
    )
    page_size = max(1, chunk_rows // (CONVERSATION_UNIT_OVERHEAD_ROWS + 1))
    return ConversationPageAllocation(
        unit_rows=unit_rows,
        unit_files=min(unit_rows, execution_files),
        chunk_rows=chunk_rows,
        page_size=page_size,
        max_batch=min(
            execution_rows, unit_rows + CONVERSATION_UNIT_OVERHEAD_ROWS * page_size
        ),
        family_rows=family_rows,
    )


async def run_conversation_page(
    repository: ConversationPageRepository,
    batch: RetentionBatch,
    allocation: ConversationPageAllocation,
    estimate: ConversationRootCostEstimate,
    *,
    gather_seconds: float,
    clock: Callable[[], float] = time.monotonic,
) -> RetentionStepResult:
    """Lock one page of due roots and delete those that fit, in keyset order.

    Charges: one row per examined discovery row and per locked, attempted or
    passed root (discovery), the child rows each proof examined, then one row for the root
    DELETE plus the emptied session and the Files work.
    A root whose children exceed a fully funded unit is blocked and passed; one
    that only lacks the chunk's remaining allowance is retried in a fresh chunk.
    The cursor is the last visited root; once every root of a page that did not
    fill its limit is visited, every examined row is done, so the cursor moves
    to the page's `done`, and a complete page also ends the pass.
    Roots after the first are admitted for `gather_seconds` from the call, and
    never at or after the execution deadline: the page's root locks are held
    until the chunk commits, so a user deleting a paged chat waits at most
    that long plus one unit.
    """
    stop_at = min(clock() + gather_seconds, batch.deadline)
    out = RetentionEffects()
    # Defer the execution tail rather than paying for one-root transactions.
    if batch.rows < allocation.unit_rows + CONVERSATION_UNIT_OVERHEAD_ROWS:
        return out.result(rows=0, exhausted=False, deferred=True, cursor=batch.cursor)

    ordinary = retention_unit_allowance(batch.rows, allocation.chunk_rows, fresh=False)
    page_size = max(
        1,
        min(
            ordinary // max(CONVERSATION_UNIT_OVERHEAD_ROWS + 1, estimate.unit_rows),
            # Discovery (at most one owner and one root per page entry) must
            # leave the first root its whole unit allowance.
            (batch.rows - allocation.unit_rows) // CONVERSATION_UNIT_OVERHEAD_ROWS,
        ),
    )
    page = await repository.lock_due_page(batch.cursor, page_size)
    roots = page.roots
    if page.done is None:
        return out.result(rows=0, exhausted=True, cursor=batch.cursor)

    locked = frozenset(page.locked_ids)
    passed = frozenset(page.passed_ids)
    rows = page.examined + len(roots)
    out.add(None, repository.examined_key, page.examined)
    files = 0
    cursor = batch.cursor
    visited = 0
    deferred = False
    for root in roots:
        # The first root always runs so every chunk makes progress.
        if visited and clock() >= stop_at:
            break
        if root.id in passed:
            cursor = root
            visited += 1
            continue
        if root.id not in locked:
            out.blocked[ConversationBlockReason.ROOT_LOCKED.key] += 1
            cursor = root
            visited += 1
            continue
        allowance = retention_unit_allowance(
            batch.rows, allocation.chunk_rows, fresh=visited == 0
        )
        remaining = min(allocation.unit_rows, allowance - rows)
        # Nothing is left for this root's DELETE in this chunk.
        if remaining < 1:
            deferred = visited == 0
            break
        # The proof leaves one row of the remaining allowance for the DELETE.
        ceiling = remaining - 1
        children = await repository.cascade_cost(root.id, ceiling)
        if children is None:
            # The root waits for a later pass, not for the session while it
            # holds the root; the attempt read the session row.
            rows += 1
            out.blocked[ConversationBlockReason.ROOT_LOCKED.key] += 1
            cursor = root
            visited += 1
            continue
        rows += children
        if children > ceiling:
            # Only a fully funded root is too large by itself; otherwise retry
            # it fresh, keeping the cursor before it.
            if remaining < allocation.unit_rows:
                deferred = visited == 0
                break
            out.blocked[ConversationBlockReason.UNIT_EXCEEDS_BUDGET.key] += 1
            cursor = root
            visited += 1
            continue
        file_allowance = min(allocation.unit_files, batch.files - files)
        unit = await repository.delete_unit(
            root.id,
            child_rows=children,
            max_rows=remaining - children,
            max_files=file_allowance,
            max_family_rows=allocation.family_rows,
        )
        rows += unit.rows
        files += unit.files
        if not unit.fits:
            # A remainder shortage retries this candidate in a fresh chunk.
            # A fully funded unit that cannot fit is revisited on the next pass.
            if (
                remaining < allocation.unit_rows
                or file_allowance < allocation.unit_files
            ):
                deferred = visited == 0
                break
            out.blocked[ConversationBlockReason.UNIT_EXCEEDS_BUDGET.key] += 1
        elif unit.block is not None:
            out.blocked[unit.block.key] += 1
        if unit.deletion is not None:
            out.add(unit.deletion.tenant_id, repository.kind.deleted_key)
            if unit.deletion.source is not None:
                out.add(
                    unit.deletion.tenant_id, f"by_{unit.deletion.source.value}_rule"
                )
            out.add(unit.deletion.tenant_id, "sessions_deleted", unit.sessions_deleted)
            out.add(unit.deletion.tenant_id, "files_deleted", unit.files_deleted)
            for reason, count in unit.file_outcomes.items():
                out.add(unit.deletion.tenant_id, reason.key, count)
        cursor = root
        visited += 1
    if visited:
        estimate.unit_rows = -(-rows // visited)
    # A root window short of its limit holds every selected root of the
    # examined rows; once all of them are visited those rows are done.
    owners_done = visited == len(roots) and len(roots) < page_size
    if owners_done:
        cursor = page.done
    return out.result(
        rows=rows,
        files=files,
        exhausted=owners_done and page.complete,
        deferred=deferred,
        cursor=cursor,
    )
