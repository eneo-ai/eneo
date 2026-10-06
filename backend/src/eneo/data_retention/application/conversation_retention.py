"""One bounded conversation page; the retention runner owns its transaction."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
    ConversationPolicySource,
    RetentionKeyset,
)


class ConversationBlockReason(StrEnum):
    UNIT_EXCEEDS_BUDGET = "unit_exceeds_budget"
    NO_LONGER_DUE = "no_longer_due"
    ROOT_LOCKED = "root_locked"


@dataclass(frozen=True, slots=True)
class ConversationDeletion:
    id: UUID
    tenant_id: UUID
    source: ConversationPolicySource


@dataclass(frozen=True, slots=True)
class ConversationPage:
    roots: Sequence[RetentionKeyset]
    locked_ids: Sequence[UUID]


class ConversationPageRepository(Protocol):
    async def lock_due_page(
        self, cursor: RetentionKeyset | None, limit: int
    ) -> ConversationPage: ...

    async def cascade_costs(
        self, ids: Sequence[UUID], ceiling: int
    ) -> Mapping[UUID, int]: ...

    async def delete_due_prefix(
        self, ids: Sequence[UUID]
    ) -> Sequence[ConversationDeletion]: ...


@dataclass(frozen=True, slots=True)
class ConversationPageAllocation:
    unit_rows: int
    chunk_rows: int
    max_batch: int


def conversation_page_allocation(
    *, unit_rows: int, chunk_rows: int, execution_rows: int
) -> ConversationPageAllocation:
    validate_conversation_unit_budget(
        unit_rows=unit_rows, execution_rows=execution_rows
    )
    page_size = max(1, chunk_rows // (CONVERSATION_UNIT_OVERHEAD_ROWS + 1))
    return ConversationPageAllocation(
        unit_rows=unit_rows,
        chunk_rows=chunk_rows,
        max_batch=min(
            execution_rows, unit_rows + CONVERSATION_UNIT_OVERHEAD_ROWS * page_size
        ),
    )


async def run_conversation_page(
    repository: ConversationPageRepository,
    batch: RetentionBatch,
    allocation: ConversationPageAllocation,
) -> RetentionStepResult:
    out = RetentionEffects()
    # Defer the execution tail rather than paying for one-root transactions.
    if batch.rows < allocation.unit_rows + CONVERSATION_UNIT_OVERHEAD_ROWS:
        return out.result(rows=0, exhausted=False, deferred=True, cursor=batch.cursor)

    # Prefetch must leave the largest first root's whole cascade allowance.
    ordinary = retention_unit_allowance(batch.rows, allocation.chunk_rows, fresh=False)
    page_size = max(
        1,
        min(
            ordinary // (CONVERSATION_UNIT_OVERHEAD_ROWS + 1),
            (batch.rows - allocation.unit_rows) // CONVERSATION_UNIT_OVERHEAD_ROWS,
        ),
    )
    page = await repository.lock_due_page(batch.cursor, page_size)
    roots = page.roots
    if not roots:
        return out.result(rows=0, exhausted=True, cursor=batch.cursor)

    costs: Mapping[UUID, int] = (
        await repository.cascade_costs(page.locked_ids, allocation.unit_rows)
        if page.locked_ids
        else {}
    )
    proof_rows = len(roots) + len(costs)
    admitted_rows = proof_rows
    prefix: list[UUID] = []
    cursor = batch.cursor
    visited = 0
    for root in roots:
        if root.id not in costs:
            out.blocked[ConversationBlockReason.ROOT_LOCKED.value] += 1
            cursor = root
            visited += 1
            continue
        cost = 1 + costs[root.id]
        if cost > allocation.unit_rows:
            out.blocked[ConversationBlockReason.UNIT_EXCEEDS_BUDGET.value] += 1
            cursor = root
            visited += 1
            continue
        allowance = retention_unit_allowance(
            batch.rows, allocation.chunk_rows, fresh=visited == 0
        )
        if admitted_rows + cost > allowance:
            break
        admitted_rows += cost
        prefix.append(root.id)
        cursor = root
        visited += 1

    deleted = await repository.delete_due_prefix(prefix) if prefix else ()
    out.blocked[ConversationBlockReason.NO_LONGER_DUE.value] += len(prefix) - len(
        deleted
    )
    rows = proof_rows
    for root in deleted:
        rows += 1 + costs[root.id]
        out.add(root.tenant_id, "conversations_deleted")
        out.add(root.tenant_id, f"by_{root.source.value}_rule")
    return out.result(
        rows=rows,
        exhausted=visited == len(roots) and len(roots) < page_size,
        cursor=cursor,
    )
