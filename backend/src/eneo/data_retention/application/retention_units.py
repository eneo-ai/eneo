"""Bounded candidate collection shared by retention task adopters.

The runner owns transactions, audit and execution budgets. This collector
selects only units it will process, gathers up to the ordinary chunk limit,
and preserves the durable cursor before an incomplete unit.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
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
    receipts: defaultdict[UUID | None, list[UUID]] = field(
        default_factory=lambda: defaultdict(list)
    )
    blocked: defaultdict[str, int] = field(default_factory=lambda: defaultdict(int))

    def add(self, tenant_id: UUID | None, key: str, value: int = 1) -> None:
        if value:
            self.counts[tenant_id][key] += value

    def add_rows(self, rows: Iterable[tuple[UUID, UUID]], key: str) -> None:
        for _, tenant_id in rows:
            self.add(tenant_id, key)

    def merge(self, committed: RetentionEffects) -> None:
        """Include a unit's effects only after its savepoint has committed."""
        for tenant_id, counts in committed.counts.items():
            for key, value in counts.items():
                self.add(tenant_id, key, value)
        for tenant_id, receipt_ids in committed.receipts.items():
            self.receipts[tenant_id].extend(receipt_ids)
        for key, value in committed.blocked.items():
            self.blocked[key] += value

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
                RetentionTenantEffect(
                    tenant_id=tenant_id,
                    counts=dict(counts),
                    receipt_ids=tuple(dict.fromkeys(self.receipts[tenant_id])),
                )
                for tenant_id, counts in self.counts.items()
            ),
            blocked={key: value for key, value in self.blocked.items() if value},
            exhausted=exhausted,
            deferred=deferred,
            cursor=cursor,
        )


RetentionUnitCandidate = tuple[
    RetentionKeyset, Callable[[int, int], Awaitable["RetentionUnitUsage"]]
]


class RetentionUnitDisposition(Enum):
    DONE = "done"
    # Committed partial work needs another fresh preparation.
    CONTINUE = "continue"
    DOES_NOT_FIT = "does_not_fit"


@dataclass(frozen=True, slots=True)
class RetentionUnitUsage:
    """Logical row and file work charged by one candidate."""

    rows: int
    files: int
    disposition: RetentionUnitDisposition = RetentionUnitDisposition.DONE


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
    min_candidate_rows: int = 1,
    clock: Callable[[], float] = time.monotonic,
) -> RetentionStepResult:
    """Gather completed units; a larger first unit may use the whole batch.

    CONTINUE leaves the cursor for another fresh preparation. DOES_NOT_FIT
    retries in a fresh chunk, or ends this step when the call already started
    fresh. The runner commits charges, audit and cursor before either stop.
    Reserve the candidate's discovery rows before selecting it. A row-only
    consumer has zero file allowance, which does not stop candidate gathering.
    """
    rows = files = 0
    started = clock()
    while True:
        fresh = rows == 0 and files == 0
        row_limit = max_rows if fresh else min(max_rows, chunk_rows)
        file_limit = max_files if fresh else min(max_files, chunk_rows)
        if row_limit - rows < min_candidate_rows:
            return out.result(
                rows=rows,
                files=files,
                exhausted=False,
                cursor=cursor,
                deferred=fresh,
            )
        if (file_limit > 0 and files >= file_limit) or (
            not fresh and clock() - started > gather_seconds
        ):
            return out.result(rows=rows, files=files, exhausted=False, cursor=cursor)
        candidate = await next_candidate(cursor)
        if candidate is None:
            return out.result(rows=rows, files=files, exhausted=True, cursor=cursor)
        keyset, handle = candidate
        spent = await handle(row_limit - rows, file_limit - files)
        if not (
            0 < spent.rows <= row_limit - rows
            and 0 <= spent.files <= file_limit - files
        ):
            raise RetentionContractError(
                "A unit must charge its admitted work within its budget."
            )
        rows += spent.rows
        files += spent.files
        if spent.disposition is not RetentionUnitDisposition.DONE:
            return out.result(
                rows=rows,
                files=files,
                exhausted=False,
                cursor=cursor,
                deferred=(
                    fresh and spent.disposition is RetentionUnitDisposition.DOES_NOT_FIT
                ),
            )
        cursor = keyset
