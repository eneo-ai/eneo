"""Run one registered retention task: exclusive claim, bounded chunks, required audit.

A task is an ordered list of steps. Every step call is one chunk: one
transaction that (1) proves the execution still owns the task (the ownership
UPDATE is its first statement after the wait limits, and its row lock lasts to
commit), (2) runs one bounded call of the step, (3) writes the required audit of
what the call deleted, one event per tenant with a deterministic id, and (4)
records progress on the job row. A failure in any part rolls the whole chunk
back, so deletions never commit without their audit or progress.

Every retention transaction (claim, chunk, finish, skip) first sets its lock and
statement timeouts, so waiting on another execution's row lock ends within the
configured limit: a claim that times out is recorded as a skipped run, a chunk
that times out or is chosen as a deadlock victim ends the run as partial, and a
finish that times out leaves the running row to the stale takeover, which
records it as superseded. A step that breaks the adopter contract ends the run
as failed with `contract_violation`, apart from database failures.

Everything a step reports is a count under a name the task declares in closed
sets: a disposal fact (`count_keys`, for example rows deleted), an observation
(`observation_keys`, for example rows examined or files kept in use) or a
blocked reason (`blocked_keys`). Disposal facts and blocked reasons are the
audit trail: a chunk that has any of them writes one audit event per tenant.
Observations are progress only; they are kept on the job row. A call that
charged rows or files must report them under some key or is refused, and a
call may not charge more than its batch allows. A step call that makes no
progress ends that step for the run (recorded as `<step>.stalled`). Explicit
deferral ends the step after committing its cursor and audit, is recorded as
the count `<step>.deferred` on the job row (a deferral disposes of nothing and
keeps nothing, so alone it writes no audit event), and lets later steps use
the remaining budget. The budget is checked before every call, and the batch
carries the execution's deadline so a step stops admitting new units at it;
the unit in progress completes within the statement timeouts.

Each step has a durable keyset cursor: the batch carries the position the
task's newest execution reached, the step returns its new position, and the
chunk persists it on the job row in the same transaction; a step whose pass is
complete (exhausted) starts the next pass from the beginning.

A task that reports overdue work (RetentionOverdueReporter) has its snapshot
written to the job row when the execution ends, whatever the outcome (budget
spent, a failed or timed-out chunk), in its own bounded transaction before the
final outcome; a superseded execution writes none. A snapshot that fails is
logged; the previous snapshot continues to age until health marks it stale.

The final outcome and one required `data_retention_run` audit event with the
execution's outcome and audited totals commit together in the finish
transaction, so an execution that was superseded or whose finish timed out
writes no event, and an outcome never commits without its event.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.audit_log import AuditLog
from eneo.audit.domain.entity_types import EntityType
from eneo.data_retention.application.retention_sql_limits import set_retention_timeouts
from eneo.data_retention.domain.retention import (
    RetentionBudget,
    RetentionErrorCode,
    RetentionJobOutcome,
    RetentionKeyset,
    RetentionOverdue,
    RetentionUsage,
    retention_batch_audit_id,
    retention_name,
    retention_run_audit_id,
    retention_summary,
)

logger = logging.getLogger(__name__)


class _TransientSQLState(StrEnum):
    """Database errors that end a chunk without a defect: the next execution
    retries the same work."""

    STATEMENT_CANCELLED = "57014"
    LOCK_NOT_AVAILABLE = "55P03"
    # A lock cycle with a user transaction (for example a manual File delete,
    # which waits on File roots without SKIP LOCKED); PostgreSQL aborts one side.
    DEADLOCK_DETECTED = "40P01"


_TIMEOUT_STATES = frozenset(
    {_TransientSQLState.STATEMENT_CANCELLED, _TransientSQLState.LOCK_NOT_AVAILABLE}
)


# The runner's own counts: a step call without progress ended the step, or the
# step deferred its remaining work to the next execution.
STALLED = "stalled"
DEFERRED = "deferred"


@dataclass(frozen=True, slots=True)
class RetentionBatch:
    job_run_id: UUID
    batch_seq: int
    rows: int
    files: int
    # When the execution's time budget ends, on the runner's monotonic clock: a
    # step admits no new unit at or after it. Absolute, so the chunk's wait for
    # its transaction and lease renewal is not given back to the step.
    deadline: float
    # Where the step's current pass stands; None starts a pass.
    cursor: RetentionKeyset | None = None


@dataclass(frozen=True, slots=True)
class RetentionTenantEffect:
    """What one step call reported for one tenant: its disposal facts (the
    tenant's audit event) and its observations (kept on the job row only).

    `tenant_id=None` is a deployment-level effect (for example pruned job runs),
    audited in the deployment's tenant.
    """

    tenant_id: UUID | None
    counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class RetentionStepResult:
    # Rows and files the call visited (budget use and progress).
    rows: int = 0
    files: int = 0
    effects: tuple[RetentionTenantEffect, ...] = ()
    blocked: Mapping[str, int] = field(default_factory=dict[str, int])
    # The pass is complete: nothing is left for this step in this run, and the
    # next execution starts a new pass.
    exhausted: bool = False
    # End this step for this execution while keeping its unfinished cursor.
    deferred: bool = False
    # The position after this call, kept for the next call and execution.
    cursor: RetentionKeyset | None = None


@dataclass(frozen=True, slots=True)
class RetentionStep:
    name: str
    run: Callable[[RetentionBatch], Awaitable[RetentionStepResult]]
    # A step whose unit of work is larger than a chunk (one whole file family)
    # asks for batches of up to this many rows and files instead.
    max_batch: int | None = None
    # The step's file allowance per batch. None gives it the same allowance as
    # its rows (max_batch, else the chunk); zero declares that this step does
    # not spend the file budget.
    max_files: int | None = None


class RetentionTask(Protocol):
    @property
    def name(self) -> str: ...

    # The closed sets of names its steps may report: disposal facts (audited),
    # observations (progress only) and blocked reasons (audited).
    @property
    def count_keys(self) -> frozenset[str]: ...

    @property
    def observation_keys(self) -> frozenset[str]: ...

    @property
    def blocked_keys(self) -> frozenset[str]: ...

    def steps(self) -> Sequence[RetentionStep]: ...


class RetentionAuditSink(Protocol):
    """Required retention events cross the audit boundary as JSON values."""

    async def log(
        self,
        *,
        tenant_id: UUID,
        actor_type: ActorType,
        action: ActionType,
        entity_type: EntityType,
        entity_id: UUID,
        description: str,
        metadata: dict[str, JsonValue],
        required: bool,
        audit_id: UUID | None = None,
    ) -> AuditLog | None: ...


@runtime_checkable
class RetentionOverdueReporter(Protocol):
    """A task whose due work can be overdue; one bounded read.

    The one owner of "this task reports overdue work": the runner records a
    snapshot for it and health expects one (overdue_reporter)."""

    async def overdue(self) -> RetentionOverdue: ...


def overdue_reporter(task: RetentionTask) -> RetentionOverdueReporter | None:
    return task if isinstance(task, RetentionOverdueReporter) else None


class RetentionJobRunStore(Protocol):
    async def claim(self, *, task: str, lease_stale_seconds: int) -> UUID | None: ...

    async def renew(self, job_run_id: UUID) -> bool: ...

    async def record_progress(
        self,
        job_run_id: UUID,
        *,
        batch_count: int,
        counts: Mapping[str, int],
        blocked: Mapping[str, int],
        cursors: Mapping[str, RetentionKeyset],
    ) -> None: ...

    async def cursors(self, job_run_id: UUID) -> dict[str, RetentionKeyset]: ...

    async def finish(
        self,
        job_run_id: UUID,
        *,
        outcome: RetentionJobOutcome,
        error_code: RetentionErrorCode | None,
    ) -> bool: ...

    async def record_skip(
        self, *, task: str, error_code: RetentionErrorCode
    ) -> UUID: ...

    async def record_overdue(
        self, job_run_id: UUID, overdue: RetentionOverdue
    ) -> bool: ...

    async def deployment_tenant_id(self) -> UUID | None: ...


@dataclass(frozen=True, slots=True)
class RetentionChunkLimits:
    rows: int
    statement_timeout_ms: int
    lock_timeout_ms: int
    lease_stale_seconds: int


@dataclass(frozen=True, slots=True)
class RetentionRunReport:
    task: str
    # None: another execution holds the task, nothing ran.
    job_run_id: UUID | None
    # RUNNING: the final outcome could not be written (error FINISH_TIMEOUT).
    outcome: RetentionJobOutcome | None
    counts: Mapping[str, int] = field(default_factory=dict[str, int])
    blocked: Mapping[str, int] = field(default_factory=dict[str, int])
    error_code: RetentionErrorCode | None = None


class RetentionOwnershipLost(RuntimeError):
    """The execution was superseded; it may no longer commit any work."""


class RetentionContractError(ValueError):
    """A step reported a name outside its task's closed sets or a negative count."""


class _ClaimLost(Exception):
    pass


def _checked(values: Mapping[str, object], allowed: frozenset[str], what: str) -> None:
    for key, value in values.items():
        # Values come from task code; check them at runtime, not only by type.
        if key not in allowed or not isinstance(value, int) or value < 0:
            raise RetentionContractError(f"Unexpected retention {what} {key!r}.")


@runtime_checkable
class _SQLStateError(Protocol):
    @property
    def sqlstate(self) -> str | None: ...


def _transient_state(exc: BaseException) -> _TransientSQLState | None:
    """The transient database state that ended `exc`, also when another error
    wraps it (a lock helper that reports a busy lock as its own error)."""
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, DBAPIError):
            if not isinstance(cause.orig, _SQLStateError):
                return None
            try:
                return _TransientSQLState(cause.orig.sqlstate)
            except ValueError:
                return None
        cause = cause.__cause__
    return None


def is_retention_timeout(exc: BaseException) -> bool:
    """A statement or lock timeout: the claim and finish wait limits."""
    return _transient_state(exc) in _TIMEOUT_STATES


def is_lock_wait_timeout(exc: BaseException) -> bool:
    """A lock wait reached the lock timeout (55P03), and no other state: a
    statement timeout or a deadlock still ends the chunk."""
    return _transient_state(exc) is _TransientSQLState.LOCK_NOT_AVAILABLE


def _chunk_ending(
    exc: Exception,
) -> tuple[RetentionJobOutcome, RetentionErrorCode]:
    if isinstance(exc, RetentionContractError):
        return RetentionJobOutcome.FAILED, RetentionErrorCode.CONTRACT_VIOLATION
    state = _transient_state(exc)
    if state is _TransientSQLState.DEADLOCK_DETECTED:
        return RetentionJobOutcome.PARTIAL, RetentionErrorCode.CHUNK_DEADLOCK
    if state is not None:
        return RetentionJobOutcome.PARTIAL, RetentionErrorCode.CHUNK_TIMEOUT
    return RetentionJobOutcome.FAILED, RetentionErrorCode.CHUNK_FAILED


def _merged(
    total: Mapping[str, int], step: str, part: Mapping[str, int]
) -> dict[str, int]:
    merged = dict(total)
    for key, value in part.items():
        if value:
            name = f"{step}.{key}"
            merged[name] = merged.get(name, 0) + value
    return merged


class RetentionRunner:
    def __init__(
        self,
        *,
        session: AsyncSession,
        job_runs: RetentionJobRunStore,
        audit_service: RetentionAuditSink,
        budget: RetentionBudget,
        limits: RetentionChunkLimits,
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
        """A retention transaction; its first statements bound every wait in it."""
        async with self.session.begin():
            await set_retention_timeouts(
                self.session,
                statement_timeout_ms=self.limits.statement_timeout_ms,
                lock_timeout_ms=self.limits.lock_timeout_ms,
            )
            yield

    async def run(self, task: RetentionTask) -> RetentionRunReport:
        try:
            async with self._transaction():
                job_run_id = await self.job_runs.claim(
                    task=task.name, lease_stale_seconds=self.limits.lease_stale_seconds
                )
                if job_run_id is None:
                    raise _ClaimLost
                cursors = await self.job_runs.cursors(job_run_id)
        except _ClaimLost:
            return RetentionRunReport(task=task.name, job_run_id=None, outcome=None)
        except Exception as exc:
            if not is_retention_timeout(exc):
                raise
            return await self._record_claim_timeout(task.name)

        progress = _Progress(started=self.clock(), cursors=cursors)
        outcome = RetentionJobOutcome.SUCCEEDED
        error_code: RetentionErrorCode | None = None
        try:
            for step in task.steps():
                if not await self._run_step(task, step, job_run_id, progress):
                    outcome = RetentionJobOutcome.PARTIAL
                if progress.budget_spent:
                    break
        except RetentionOwnershipLost:
            logger.warning("Retention task %s was superseded; stopping.", task.name)
            return RetentionRunReport(
                task=task.name,
                job_run_id=job_run_id,
                outcome=RetentionJobOutcome.SUPERSEDED,
                counts=progress.counts,
                blocked=progress.blocked,
            )
        except Exception as exc:
            outcome, error_code = _chunk_ending(exc)
            if outcome is RetentionJobOutcome.PARTIAL:
                logger.warning(
                    "Retention task %s chunk %s ended: %s",
                    task.name,
                    progress.batch_seq,
                    error_code.value,
                )
            else:
                logger.exception(
                    "Retention task %s chunk %s failed: %s",
                    task.name,
                    progress.batch_seq,
                    error_code.value,
                )

        reporter = overdue_reporter(task)
        if reporter is not None:
            await self._record_overdue(task.name, reporter, job_run_id)

        try:
            async with self._transaction():
                finished = await self.job_runs.finish(
                    job_run_id, outcome=outcome, error_code=error_code
                )
                if finished:
                    await self._audit_run(
                        task.name, job_run_id, outcome, error_code, progress
                    )
        except Exception as exc:
            if not is_retention_timeout(exc):
                raise
            logger.warning(
                "Retention task %s could not record its outcome %s in time; the "
                "stale takeover records the execution.",
                task.name,
                outcome.value,
            )
            return RetentionRunReport(
                task=task.name,
                job_run_id=job_run_id,
                outcome=RetentionJobOutcome.RUNNING,
                counts=progress.counts,
                blocked=progress.blocked,
                error_code=RetentionErrorCode.FINISH_TIMEOUT,
            )
        if not finished:
            outcome = RetentionJobOutcome.SUPERSEDED
        return RetentionRunReport(
            task=task.name,
            job_run_id=job_run_id,
            outcome=outcome,
            counts=progress.counts,
            blocked=progress.blocked,
            error_code=error_code,
        )

    async def _run_step(
        self,
        task: RetentionTask,
        step: RetentionStep,
        job_run_id: UUID,
        progress: _Progress,
    ) -> bool:
        """Call the step until it is exhausted; False if it ended early."""
        retention_name(step.name)
        while True:
            elapsed = self.clock() - progress.started
            left = self.budget.left(progress.used, elapsed_seconds=elapsed)
            if left.rows == 0:
                progress.budget_spent = True
                return False
            progress.batch_seq += 1
            batch = RetentionBatch(
                job_run_id=job_run_id,
                batch_seq=progress.batch_seq,
                rows=min(step.max_batch or self.limits.rows, left.rows),
                deadline=progress.started + self.budget.seconds,
                files=min(
                    step.max_files
                    if step.max_files is not None
                    else step.max_batch or self.limits.rows,
                    left.files,
                ),
                cursor=progress.cursors.get(step.name),
            )
            async with self._transaction():
                result = await self._chunk(task, step, batch)
                stalled = (
                    not result.exhausted
                    and not result.deferred
                    and result.rows == 0
                    and result.files == 0
                )
                totals = _effect_totals(result)
                counts = _merged(
                    progress.counts,
                    step.name,
                    {
                        **totals,
                        **({STALLED: 1} if stalled else {}),
                        **({DEFERRED: 1} if result.deferred else {}),
                    },
                )
                blocked = _merged(progress.blocked, step.name, result.blocked)
                disposed = {
                    key: value
                    for key, value in totals.items()
                    if value and key in task.count_keys
                }
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
            progress.disposed = _merged(progress.disposed, step.name, disposed)
            progress.disposal_totals = _summed(progress.disposal_totals, disposed)
            progress.cursors = cursors
            progress.used = progress.used.plus(rows=result.rows, files=result.files)
            if result.exhausted:
                return True
            if result.deferred:
                return False
            if stalled:
                logger.warning(
                    "Retention step %s.%s made no progress; ended for this run.",
                    task.name,
                    step.name,
                )
                return False

    async def _record_overdue(
        self, name: str, reporter: RetentionOverdueReporter, job_run_id: UUID
    ) -> None:
        """Write the task's overdue snapshot on its own row; never fails the run.

        The deletions already committed stand on their own; a snapshot that is
        not written leaves the newest one to age. Health reports overdue_unknown
        (RETENTION_OVERDUE) once that snapshot passes its freshness threshold."""
        try:
            async with self._transaction():
                overdue = await reporter.overdue()
                if not await self.job_runs.record_overdue(job_run_id, overdue):
                    logger.warning(
                        "Retention task %s was superseded; no overdue snapshot.", name
                    )
        except Exception:
            logger.exception("Retention task %s could not record overdue work.", name)

    async def _audit_run(
        self,
        task: str,
        job_run_id: UUID,
        outcome: RetentionJobOutcome,
        error_code: RetentionErrorCode | None,
        progress: _Progress,
    ) -> None:
        """The execution's required end event, in its finish transaction: what an
        administrator reads first (outcome and totals) instead of every chunk."""
        tenant_id = await self.job_runs.deployment_tenant_id()
        if tenant_id is None:
            # An outcome without its required audit event would be silent.
            raise RetentionContractError("No tenant to hold the retention audit event.")
        ending = (
            f"{outcome.value} ({error_code.value})"
            if error_code is not None
            else outcome.value
        )
        await self.audit_service.log(
            audit_id=retention_run_audit_id(job_run_id),
            tenant_id=tenant_id,
            actor_type=ActorType.SYSTEM,
            action=ActionType.DATA_RETENTION_RUN,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=tenant_id,
            description=(
                f"Retention {task} finished: {ending}; "
                f"{retention_summary(progress.disposal_totals, progress.blocked)}"
            ),
            metadata={
                "task": task,
                "job_run_id": str(job_run_id),
                "outcome": outcome.value,
                "error_code": error_code.value if error_code is not None else None,
                "counts": dict(progress.disposed),
                "blocked": dict(progress.blocked),
                "batch_count": progress.batch_seq,
            },
            required=True,
        )

    async def skip(self, task: str) -> RetentionRunReport:
        """Record a run the deployment's emergency switch suppressed; never silent.

        One transaction: a skipped job row and a required system audit event in
        the deployment's tenant.
        """
        reason = RetentionErrorCode.DISABLED_BY_DEPLOYMENT_SETTING
        async with self._transaction():
            tenant_id = await self.job_runs.deployment_tenant_id()
            if tenant_id is None:
                # A suppressed run without its required audit event would be silent.
                raise RetentionContractError(
                    "No tenant to hold the retention audit event."
                )
            job_run_id = await self.job_runs.record_skip(task=task, error_code=reason)
            await self.audit_service.log(
                audit_id=retention_batch_audit_id(
                    job_run_id=job_run_id, batch_seq=0, tenant_id=tenant_id
                ),
                tenant_id=tenant_id,
                actor_type=ActorType.SYSTEM,
                action=ActionType.DATA_RETENTION_SKIPPED,
                entity_type=EntityType.TENANT_SETTINGS,
                entity_id=tenant_id,
                description=(
                    f"Retention {task} skipped: turned off by a deployment setting."
                ),
                metadata={
                    "task": task,
                    "job_run_id": str(job_run_id),
                    "reason": reason.value,
                },
                required=True,
            )
        logger.warning(
            "Retention task %s skipped: turned off by a deployment setting.", task
        )
        return RetentionRunReport(
            task=task,
            job_run_id=job_run_id,
            outcome=RetentionJobOutcome.SKIPPED,
            error_code=reason,
        )

    async def _record_claim_timeout(self, task: str) -> RetentionRunReport:
        """Record a run that did not start because its claim timed out; no audit
        event, as nothing ran and the job row holds the reason."""
        error_code = RetentionErrorCode.CLAIM_TIMEOUT
        logger.warning("Retention task %s not started: %s.", task, error_code.value)
        async with self._transaction():
            job_run_id = await self.job_runs.record_skip(
                task=task, error_code=error_code
            )
        return RetentionRunReport(
            task=task,
            job_run_id=job_run_id,
            outcome=RetentionJobOutcome.SKIPPED,
            error_code=error_code,
        )

    async def _chunk(
        self, task: RetentionTask, step: RetentionStep, batch: RetentionBatch
    ) -> RetentionStepResult:
        # The ownership check is the first statement after the wait limits.
        if not await self.job_runs.renew(batch.job_run_id):
            raise RetentionOwnershipLost(batch.job_run_id)
        result = await step.run(batch)
        if result.deferred and result.exhausted:
            raise RetentionContractError("A step cannot be exhausted and deferred.")
        if not (0 <= result.rows <= batch.rows and 0 <= result.files <= batch.files):
            raise RetentionContractError("A step call charged more than its batch.")
        _checked(result.blocked, task.blocked_keys, "blocked count")
        reported = bool(result.blocked) or result.deferred
        for effect in result.effects:
            _checked(effect.counts, task.count_keys | task.observation_keys, "count")
            reported = reported or any(effect.counts.values())
        if (result.rows or result.files) and not reported:
            # Whatever the call examined or wrote is in its counts.
            raise RetentionContractError("A step call charged work it did not report.")
        events = await self._audit_events(result, task.count_keys)
        for event in events:
            await self._audit(task=task.name, step=step.name, batch=batch, event=event)
        return result

    async def _audit_events(
        self, result: RetentionStepResult, audited: frozenset[str]
    ) -> list[_AuditEvent]:
        """One event per audit tenant with disposal facts or blocked reasons: the
        audit id is derived from the batch and the tenant, so effects that resolve
        to the same tenant are merged first. Observations are not audited.
        Blocked counts belong to the deployment and go in its tenant's event."""
        events: dict[UUID, _AuditEvent] = {}
        deployment: list[UUID] = []

        async def deployment_tenant_id() -> UUID:
            if not deployment:
                tenant_id = await self.job_runs.deployment_tenant_id()
                if tenant_id is None:
                    raise RetentionContractError(
                        "No tenant to hold the retention audit event."
                    )
                deployment.append(tenant_id)
            return deployment[0]

        def merge(tenant_id: UUID, event: _AuditEvent) -> None:
            earlier = events.get(tenant_id)
            if earlier is not None:
                event = _AuditEvent(
                    tenant_id=tenant_id,
                    counts=_summed(earlier.counts, event.counts),
                    blocked=_summed(earlier.blocked, event.blocked),
                )
            events[tenant_id] = event

        for effect in result.effects:
            removed = {
                key: value
                for key, value in effect.counts.items()
                if value and key in audited
            }
            if not removed:
                continue
            tenant_id = (
                effect.tenant_id
                if effect.tenant_id is not None
                else await deployment_tenant_id()
            )
            merge(tenant_id, _AuditEvent(tenant_id=tenant_id, counts=removed))
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
        batch: RetentionBatch,
        event: _AuditEvent,
    ) -> None:
        tenant_id = event.tenant_id
        await self.audit_service.log(
            audit_id=retention_batch_audit_id(
                job_run_id=batch.job_run_id,
                batch_seq=batch.batch_seq,
                tenant_id=tenant_id,
            ),
            tenant_id=tenant_id,
            actor_type=ActorType.SYSTEM,
            action=ActionType.DATA_RETENTION_BATCH,
            entity_type=EntityType.TENANT_SETTINGS,
            entity_id=tenant_id,
            description=(
                f"Retention {task}, step {step}: "
                f"{retention_summary(event.counts, event.blocked)}"
            ),
            metadata={
                "task": task,
                "step": step,
                "job_run_id": str(batch.job_run_id),
                "batch_seq": batch.batch_seq,
                "counts": dict(event.counts),
                "blocked": dict(event.blocked),
            },
            required=True,
        )


@dataclass(frozen=True, slots=True)
class _AuditEvent:
    tenant_id: UUID
    counts: Mapping[str, int] = field(default_factory=dict[str, int])
    blocked: Mapping[str, int] = field(default_factory=dict[str, int])


@dataclass
class _Progress:
    started: float
    used: RetentionUsage = field(default_factory=RetentionUsage)
    counts: dict[str, int] = field(default_factory=dict[str, int])
    blocked: dict[str, int] = field(default_factory=dict[str, int])
    # The audited disposal facts by `<step>.<key>`, and summed over the steps
    # by key for the end event's description.
    disposed: dict[str, int] = field(default_factory=dict[str, int])
    disposal_totals: dict[str, int] = field(default_factory=dict[str, int])
    batch_seq: int = 0
    budget_spent: bool = False
    cursors: dict[str, RetentionKeyset] = field(
        default_factory=dict[str, RetentionKeyset]
    )


def _summed(*parts: Mapping[str, int]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for part in parts:
        for key, value in part.items():
            totals[key] = totals.get(key, 0) + value
    return totals


def _effect_totals(result: RetentionStepResult) -> dict[str, int]:
    return _summed(*(effect.counts for effect in result.effects))
