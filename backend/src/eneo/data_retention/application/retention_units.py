"""Bounded candidate collection shared by retention task adopters.

The runner owns transactions, audit and execution budgets. This collector
selects only units it will process, gathers up to the ordinary chunk limit,
and preserves the durable cursor before an incomplete unit.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol
from uuid import UUID

from eneo.data_retention.application.retention_runner import (
    RetentionContractError,
    RetentionStepResult,
    RetentionTenantEffect,
)
from eneo.data_retention.domain.retention import RetentionKeyset


@dataclass
class RetentionEffects:
    """One step call's audited effects per tenant and its blocked counts."""

    counts: defaultdict[UUID | None, defaultdict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    blocked: defaultdict[str, int] = field(default_factory=lambda: defaultdict(int))

    def add(self, tenant_id: UUID | None, key: str, value: int = 1) -> None:
        if value:
            self.counts[tenant_id][key] += value

    def result(
        self,
        *,
        rows: int,
        files: int = 0,
        exhausted: bool,
        deferred: bool = False,
        cursor: RetentionKeyset | None = None,
    ) -> RetentionStepResult:
        return RetentionStepResult(
            rows=rows,
            files=files,
            effects=tuple(
                RetentionTenantEffect(tenant_id=tenant_id, counts=dict(counts))
                for tenant_id, counts in self.counts.items()
            ),
            blocked={key: value for key, value in self.blocked.items() if value},
            exhausted=exhausted,
            deferred=deferred,
            cursor=cursor,
        )


class RetentionUnitHandle(Protocol):
    """Process one candidate unit within `rows` and `files`, the work it may
    still charge in this call; it reports what it charged."""

    def __call__(self, *, rows: int, files: int) -> Awaitable[RetentionUnitUsage]: ...


RetentionUnitCandidate = tuple[RetentionKeyset, RetentionUnitHandle]


class RetentionUnitDisposition(Enum):
    DONE = "done"
    DOES_NOT_FIT = "does_not_fit"


@dataclass(frozen=True, slots=True)
class RetentionUnitUsage:
    """Logical row and file work charged by one candidate."""

    rows: int
    files: int
    disposition: RetentionUnitDisposition = RetentionUnitDisposition.DONE


def retention_unit_allowance(maximum: int, chunk: int, *, fresh: bool) -> int:
    """An atomic first unit can use the batch; later units share the chunk."""
    return maximum if fresh else min(maximum, chunk)


async def gather_retention_units(
    next_candidate: Callable[
        [RetentionKeyset | None], Awaitable[RetentionUnitCandidate | None]
    ],
    out: RetentionEffects,
    *,
    max_rows: int,
    max_files: int,
    cursor: RetentionKeyset | None,
    chunk_rows: int,
    gather_seconds: float,
    deadline: float,
    clock: Callable[[], float] = time.monotonic,
) -> RetentionStepResult:
    """Gather completed units; a larger first unit may use the whole batch.

    DOES_NOT_FIT retries in a fresh chunk, or ends this step when the call
    already started fresh. The runner commits charges, audit and cursor before
    the step stops. A row-only consumer has zero file allowance, which does not
    stop candidate gathering.
    """
    rows = files = 0
    # Gathering ends after its own window or at the execution's deadline.
    stop_at = min(clock() + gather_seconds, deadline)
    while True:
        fresh = rows == 0 and files == 0
        row_limit = retention_unit_allowance(max_rows, chunk_rows, fresh=fresh)
        file_limit = retention_unit_allowance(max_files, chunk_rows, fresh=fresh)
        # Every candidate charges at least its discovery row.
        if (
            row_limit <= rows
            or (file_limit > 0 and files >= file_limit)
            or (not fresh and clock() >= stop_at)
        ):
            return out.result(rows=rows, files=files, exhausted=False, cursor=cursor)
        candidate = await next_candidate(cursor)
        if candidate is None:
            return out.result(rows=rows, files=files, exhausted=True, cursor=cursor)
        keyset, handle = candidate
        spent = await handle(rows=row_limit - rows, files=file_limit - files)
        if not (
            0 < spent.rows <= row_limit - rows
            and 0 <= spent.files <= file_limit - files
        ):
            raise RetentionContractError(
                "A unit must charge its admitted work within its budget."
            )
        rows += spent.rows
        files += spent.files
        if spent.disposition is RetentionUnitDisposition.DOES_NOT_FIT:
            return out.result(
                rows=rows, files=files, exhausted=False, cursor=cursor, deferred=fresh
            )
        cursor = keyset
