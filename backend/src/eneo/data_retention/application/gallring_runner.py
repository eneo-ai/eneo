"""Run one registered gallring task: exclusive claim, bounded chunks, required audit.

A task is an ordered list of steps. Every step call is one chunk: one
transaction that (1) proves the execution still owns the task (the ownership
UPDATE is its first statement after the wait limits, and its row lock lasts to
commit), (2) runs one bounded call of the step, (3) writes the required audit of
what the call deleted, one event per tenant with a deterministic id, and (4)
records progress on the job row. A failure in any part rolls the whole chunk
back, so deletions never commit without their audit or progress.

Every gallring transaction (claim, chunk, finish, skip) first sets its lock and
statement timeouts, so waiting on another execution's row lock ends within the
configured limit: a claim that times out is recorded as a skipped run, a chunk
that times out ends the run as partial, and a finish that times out leaves the
running row to the stale takeover, which records it as superseded.

Everything a step reports is either an audited effect or a blocked count, under
names the task declares in closed sets. A call that charged rows or files writes
an audit event (its effects and its blocked counts) or is refused, and a call
may not charge more than its batch allows. A step call that makes no progress
ends that step for the run (recorded as `<step>.stalled`), and the budget is
checked before every call.

Each step has a durable keyset cursor: the batch carries the position the
task's newest execution reached, the step returns its new position, and the
chunk persists it on the job row in the same transaction; a step whose pass is
complete (exhausted) starts the next pass from the beginning.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.data_retention.domain.gallring import (
    GallringBudget,
    GallringErrorCode,
    GallringJobOutcome,
    GallringKeyset,
    GallringUsage,
    gallring_batch_audit_id,
    gallring_name,
)

logger = logging.getLogger(__name__)

_TIMEOUT_SQLSTATES = frozenset({"57014", "55P03"})  # statement / lock timeout
# The runner's own count: a step call without progress ended the step.
STALLED = "stalled"


@dataclass(frozen=True, slots=True)
class GallringBatch:
    job_run_id: UUID
    batch_seq: int
    rows: int
    files: int
    # Where the step's current pass stands; None starts a pass.
    cursor: GallringKeyset | None = None


@dataclass(frozen=True, slots=True)
class GallringTenantEffect:
    """What one step call removed for one tenant; that tenant's audit event.

    `tenant_id=None` is a deployment-level effect (for example pruned job runs),
    audited in the deployment's tenant.
    """

    tenant_id: UUID | None
    counts: Mapping[str, int]
    receipt_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class GallringStepResult:
    # Rows and files the call visited (budget use and progress).
    rows: int = 0
    files: int = 0
    effects: tuple[GallringTenantEffect, ...] = ()
    blocked: Mapping[str, int] = field(default_factory=dict[str, int])
    # The pass is complete: nothing is left for this step in this run, and the
    # next execution starts a new pass.
    exhausted: bool = False
    # The position after this call, kept for the next call and execution.
    cursor: GallringKeyset | None = None


@dataclass(frozen=True, slots=True)
class GallringStep:
    name: str
    run: Callable[[GallringBatch], Awaitable[GallringStepResult]]
    # A step whose unit of work is larger than a chunk (one whole file family)
    # asks for batches of up to this many rows and files instead.
    max_batch: int | None = None


class GallringTask(Protocol):
    @property
    def name(self) -> str: ...

    # The closed sets of names its steps may report.
    @property
    def count_keys(self) -> frozenset[str]: ...

    @property
    def blocked_keys(self) -> frozenset[str]: ...

    def steps(self) -> Sequence[GallringStep]: ...


class GallringJobRunStore(Protocol):
    async def claim(self, *, task: str, stale_after_seconds: int) -> UUID | None: ...

    async def renew(self, job_run_id: UUID) -> bool: ...

    async def record_progress(
        self,
        job_run_id: UUID,
        *,
        batch_count: int,
        counts: Mapping[str, int],
        blocked: Mapping[str, int],
        cursors: Mapping[str, GallringKeyset],
    ) -> None: ...

    async def cursors(self, job_run_id: UUID) -> dict[str, GallringKeyset]: ...

    async def finish(
        self,
        job_run_id: UUID,
        *,
        outcome: GallringJobOutcome,
        error_code: GallringErrorCode | None,
    ) -> bool: ...

    async def record_skip(
        self, *, task: str, error_code: GallringErrorCode
    ) -> UUID: ...

    async def deployment_tenant_id(self) -> UUID | None: ...


@dataclass(frozen=True, slots=True)
class GallringChunkLimits:
    rows: int
    statement_timeout_ms: int
    lock_timeout_ms: int
    stale_after_seconds: int


@dataclass(frozen=True, slots=True)
class GallringRunReport:
    task: str
    # None: another execution holds the task, nothing ran.
    job_run_id: UUID | None
    # RUNNING: the final outcome could not be written (error FINISH_TIMEOUT).
    outcome: GallringJobOutcome | None
    counts: Mapping[str, int] = field(default_factory=dict[str, int])
    blocked: Mapping[str, int] = field(default_factory=dict[str, int])
    error_code: GallringErrorCode | None = None


class GallringOwnershipLost(RuntimeError):
    """The execution was superseded; it may no longer commit any work."""


class GallringContractError(ValueError):
    """A step reported a name outside its task's closed sets or a negative count."""


class _ClaimLost(Exception):
    pass


def _checked(
    values: Mapping[str, int], allowed: frozenset[str], what: str
) -> Mapping[str, int]:
    for key, value in values.items():
        # Values come from task code; check them at runtime, not only by type.
        if key not in allowed or not isinstance(cast(object, value), int) or value < 0:
            raise GallringContractError(f"Unexpected gallring {what} {key!r}.")
    return values


def _timed_out(exc: BaseException) -> bool:
    """A statement or lock timeout, also when another error wraps it (a lock
    helper that reports a busy lock as its own error)."""
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, DBAPIError):
            return getattr(cause.orig, "sqlstate", None) in _TIMEOUT_SQLSTATES
        cause = cause.__cause__
    return False


def _merged(
    total: Mapping[str, int], step: str, part: Mapping[str, int]
) -> dict[str, int]:
    merged = dict(total)
    for key, value in part.items():
        if value:
            name = f"{step}.{key}"
            merged[name] = merged.get(name, 0) + value
    return merged


class GallringRunner:
    def __init__(
        self,
        *,
        session: AsyncSession,
        job_runs: GallringJobRunStore,
        audit_service: AuditService,
        budget: GallringBudget,
        limits: GallringChunkLimits,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session
        self.job_runs = job_runs
        self.audit_service = audit_service
        self.budget = budget
        self.limits = limits
        self.clock = clock

    @asynccontextmanager
    async def _transaction(self) -> AsyncGenerator[None]:
        """A gallring transaction; its first statements bound every wait in it."""
        async with self.session.begin():
            await self.session.execute(
                text(f"SET LOCAL lock_timeout = {int(self.limits.lock_timeout_ms)}")
            )
            await self.session.execute(
                text(
                    "SET LOCAL statement_timeout = "
                    f"{int(self.limits.statement_timeout_ms)}"
                )
            )
            yield

    async def run(self, task: GallringTask) -> GallringRunReport:
        try:
            async with self._transaction():
                job_run_id = await self.job_runs.claim(
                    task=task.name, stale_after_seconds=self.limits.stale_after_seconds
                )
                if job_run_id is None:
                    raise _ClaimLost
                cursors = await self.job_runs.cursors(job_run_id)
        except _ClaimLost:
            return GallringRunReport(task=task.name, job_run_id=None, outcome=None)
        except Exception as exc:
            if not _timed_out(exc):
                raise
            return await self._record(task.name, GallringErrorCode.CLAIM_TIMEOUT)

        progress = _Progress(started=self.clock(), cursors=cursors)
        outcome = GallringJobOutcome.SUCCEEDED
        error_code: GallringErrorCode | None = None
        try:
            for step in task.steps():
                if not await self._run_step(task, step, job_run_id, progress):
                    outcome = GallringJobOutcome.PARTIAL
                if progress.budget_spent:
                    break
        except GallringOwnershipLost:
            logger.warning("Gallring task %s was superseded; stopping.", task.name)
            return GallringRunReport(
                task=task.name,
                job_run_id=job_run_id,
                outcome=GallringJobOutcome.SUPERSEDED,
                counts=progress.counts,
                blocked=progress.blocked,
            )
        except Exception as exc:
            if _timed_out(exc):
                outcome = GallringJobOutcome.PARTIAL
                error_code = GallringErrorCode.CHUNK_TIMEOUT
                logger.warning(
                    "Gallring task %s chunk %s ended: %s",
                    task.name,
                    progress.batch_seq,
                    error_code.value,
                )
            else:
                outcome = GallringJobOutcome.FAILED
                error_code = GallringErrorCode.CHUNK_FAILED
                logger.exception(
                    "Gallring task %s chunk %s failed", task.name, progress.batch_seq
                )

        try:
            async with self._transaction():
                finished = await self.job_runs.finish(
                    job_run_id, outcome=outcome, error_code=error_code
                )
        except Exception as exc:
            if not _timed_out(exc):
                raise
            logger.warning(
                "Gallring task %s could not record its outcome %s in time; the "
                "stale takeover records the execution.",
                task.name,
                outcome.value,
            )
            return GallringRunReport(
                task=task.name,
                job_run_id=job_run_id,
                outcome=GallringJobOutcome.RUNNING,
                counts=progress.counts,
                blocked=progress.blocked,
                error_code=GallringErrorCode.FINISH_TIMEOUT,
            )
        if not finished:
            outcome = GallringJobOutcome.SUPERSEDED
        return GallringRunReport(
            task=task.name,
            job_run_id=job_run_id,
            outcome=outcome,
            counts=progress.counts,
            blocked=progress.blocked,
            error_code=error_code,
        )

    async def _run_step(
        self,
        task: GallringTask,
        step: GallringStep,
        job_run_id: UUID,
        progress: _Progress,
    ) -> bool:
        """Call the step until it is exhausted; False if it ended early."""
        gallring_name(step.name)
        while True:
            left = self.budget.left(
                progress.used, elapsed_seconds=self.clock() - progress.started
            )
            if left.rows == 0:
                progress.budget_spent = True
                return False
            progress.batch_seq += 1
            batch = GallringBatch(
                job_run_id=job_run_id,
                batch_seq=progress.batch_seq,
                rows=min(step.max_batch or self.limits.rows, left.rows),
                files=min(step.max_batch or self.limits.rows, left.files),
                cursor=progress.cursors.get(step.name),
            )
            async with self._transaction():
                result = await self._chunk(task, step, batch)
                stalled = (
                    not result.exhausted and result.rows == 0 and result.files == 0
                )
                counts = _merged(
                    progress.counts,
                    step.name,
                    {
                        **_effect_totals(result),
                        **({STALLED: 1} if stalled else {}),
                    },
                )
                blocked = _merged(progress.blocked, step.name, result.blocked)
                cursors = dict(progress.cursors)
                if result.exhausted:
                    cursors.pop(step.name, None)
                elif result.cursor is not None:
                    cursors[step.name] = result.cursor
                await self.job_runs.record_progress(
                    job_run_id,
                    batch_count=progress.batch_seq,
                    counts=counts,
                    blocked=blocked,
                    cursors=cursors,
                )
            progress.counts, progress.blocked = counts, blocked
            progress.cursors = cursors
            progress.used = progress.used.plus(rows=result.rows, files=result.files)
            if result.exhausted:
                return True
            if stalled:
                logger.warning(
                    "Gallring step %s.%s made no progress; ended for this run.",
                    task.name,
                    step.name,
                )
                return False

    async def skip(self, task: str) -> GallringRunReport:
        """Record a run the deployment's emergency switch suppressed; never silent.

        One transaction: a skipped job row and a required system audit event in
        the deployment's tenant.
        """
        reason = GallringErrorCode.DISABLED_BY_DEPLOYMENT_SETTING
        async with self._transaction():
            tenant_id = await self.job_runs.deployment_tenant_id()
            if tenant_id is None:
                # A suppressed run without its required audit event would be silent.
                raise GallringContractError(
                    "No tenant to hold the gallring audit event."
                )
            job_run_id = await self.job_runs.record_skip(task=task, error_code=reason)
            await self.audit_service.log(
                audit_id=gallring_batch_audit_id(
                    job_run_id=job_run_id, batch_seq=0, tenant_id=tenant_id
                ),
                tenant_id=tenant_id,
                actor_type=ActorType.SYSTEM,
                action=ActionType.GALLRING_SKIPPED,
                entity_type=EntityType.TENANT_SETTINGS,
                entity_id=tenant_id,
                description=(
                    f"Gallring {task} skipped: disabled by deployment setting."
                ),
                metadata={
                    "task": task,
                    "job_run_id": str(job_run_id),
                    "reason": reason.value,
                },
                required=True,
            )
        logger.warning(
            "Gallring task %s skipped: disabled by deployment setting.", task
        )
        return GallringRunReport(
            task=task,
            job_run_id=job_run_id,
            outcome=GallringJobOutcome.SKIPPED,
            error_code=reason,
        )

    async def _record(
        self, task: str, error_code: GallringErrorCode
    ) -> GallringRunReport:
        """Record a run that did not start because its claim timed out."""
        logger.warning("Gallring task %s not started: %s.", task, error_code.value)
        async with self._transaction():
            job_run_id = await self.job_runs.record_skip(
                task=task, error_code=error_code
            )
        return GallringRunReport(
            task=task,
            job_run_id=job_run_id,
            outcome=GallringJobOutcome.SKIPPED,
            error_code=error_code,
        )

    async def _chunk(
        self, task: GallringTask, step: GallringStep, batch: GallringBatch
    ) -> GallringStepResult:
        # The ownership check is the first statement after the wait limits.
        if not await self.job_runs.renew(batch.job_run_id):
            raise GallringOwnershipLost(batch.job_run_id)
        result = await step.run(batch)
        if not (0 <= result.rows <= batch.rows and 0 <= result.files <= batch.files):
            raise GallringContractError("A step call charged more than its batch.")
        _checked(result.blocked, task.blocked_keys, "blocked count")
        for effect in result.effects:
            _checked(effect.counts, task.count_keys, "count")
        events = await self._audit_events(result)
        if (result.rows or result.files) and not events:
            # Whatever the call examined or wrote is in its audit event.
            raise GallringContractError("A step call charged work it did not report.")
        for event in events:
            await self._audit(task=task.name, step=step.name, batch=batch, event=event)
        return result

    async def _audit_events(self, result: GallringStepResult) -> list[_AuditEvent]:
        """One event per audit tenant: the audit id is derived from the batch and
        the tenant, so effects that resolve to the same tenant are merged first.
        Blocked counts belong to the deployment and go in its tenant's event."""
        events: dict[UUID, _AuditEvent] = {}
        deployment: list[UUID] = []

        async def deployment_tenant_id() -> UUID:
            if not deployment:
                tenant_id = await self.job_runs.deployment_tenant_id()
                if tenant_id is None:
                    raise GallringContractError(
                        "No tenant to hold the gallring audit event."
                    )
                deployment.append(tenant_id)
            return deployment[0]

        def merge(tenant_id: UUID, event: _AuditEvent) -> None:
            earlier = events.get(tenant_id)
            if earlier is not None:
                event = _AuditEvent(
                    tenant_id=tenant_id,
                    counts=_summed(earlier.counts, event.counts),
                    receipt_ids=tuple(
                        dict.fromkeys((*earlier.receipt_ids, *event.receipt_ids))
                    ),
                    blocked=_summed(earlier.blocked, event.blocked),
                )
            events[tenant_id] = event

        for effect in result.effects:
            removed = {key: value for key, value in effect.counts.items() if value}
            if not removed:
                continue
            tenant_id = (
                effect.tenant_id
                if effect.tenant_id is not None
                else await deployment_tenant_id()
            )
            merge(
                tenant_id,
                _AuditEvent(
                    tenant_id=tenant_id, counts=removed, receipt_ids=effect.receipt_ids
                ),
            )
        blocked = {key: value for key, value in result.blocked.items() if value}
        if blocked:
            tenant_id = await deployment_tenant_id()
            merge(tenant_id, _AuditEvent(tenant_id=tenant_id, blocked=blocked))
        return list(events.values())

    async def _audit(
        self,
        *,
        task: str,
        step: str,
        batch: GallringBatch,
        event: _AuditEvent,
    ) -> None:
        tenant_id = event.tenant_id
        await self.audit_service.log(
            audit_id=gallring_batch_audit_id(
                job_run_id=batch.job_run_id,
                batch_seq=batch.batch_seq,
                tenant_id=tenant_id,
            ),
            tenant_id=tenant_id,
            actor_type=ActorType.SYSTEM,
            action=ActionType.GALLRING_APPLIED,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=tenant_id,
            description=f"Scheduled gallring {task} ran its {step} step.",
            metadata={
                "task": task,
                "step": step,
                "job_run_id": str(batch.job_run_id),
                "batch_seq": batch.batch_seq,
                "counts": dict(event.counts),
                "blocked": dict(event.blocked),
                "receipt_ids": [str(receipt_id) for receipt_id in event.receipt_ids],
            },
            required=True,
        )


@dataclass(frozen=True, slots=True)
class _AuditEvent:
    tenant_id: UUID
    counts: Mapping[str, int] = field(default_factory=dict[str, int])
    receipt_ids: tuple[UUID, ...] = ()
    blocked: Mapping[str, int] = field(default_factory=dict[str, int])


@dataclass
class _Progress:
    started: float
    used: GallringUsage = field(default_factory=GallringUsage)
    counts: dict[str, int] = field(default_factory=dict[str, int])
    blocked: dict[str, int] = field(default_factory=dict[str, int])
    batch_seq: int = 0
    budget_spent: bool = False
    cursors: dict[str, GallringKeyset] = field(
        default_factory=dict[str, GallringKeyset]
    )


def _summed(*parts: Mapping[str, int]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for part in parts:
        for key, value in part.items():
            totals[key] = totals.get(key, 0) + value
    return totals


def _effect_totals(result: GallringStepResult) -> dict[str, int]:
    return _summed(*(effect.counts for effect in result.effects))
