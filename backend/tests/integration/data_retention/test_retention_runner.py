"""Existing runner contracts on PostgreSQL, using completed job rows as work items.

No product or receipt schema participates in the task's deletion side effect.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from eneo.data_retention.application.job_history_retention_task import (
    JobHistoryRetentionTask,
)
from eneo.data_retention.application.retention_health import (
    RetentionHealthStatus,
    load_retention_health,
)
from eneo.data_retention.application.retention_registration import (
    RetentionTaskRegistration,
)
from eneo.data_retention.application.retention_runner import (
    RetentionBatch,
    RetentionChunkLimits,
    RetentionRunner,
    RetentionRunReport,
    RetentionStep,
    RetentionStepResult,
    RetentionTenantEffect,
)
from eneo.data_retention.domain.retention import (
    RetentionBudget,
    RetentionErrorCode,
    RetentionJobOutcome,
    RetentionKeyset,
    RetentionOverdue,
    retention_batch_audit_id,
    retention_run_audit_id,
)
from eneo.data_retention.infrastructure.retention_job_run_repo import (
    RetentionJobRunRepository,
)
from eneo.data_retention.infrastructure.retention_sql import uuid_in
from eneo.data_retention.infrastructure.retention_worker import run_registered_tasks
from eneo.database.database import sessionmanager
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from eneo.database.tables.retention_tables import RetentionJobRuns

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

_TASK = "tests.fake"
_ITEMS_TASK = "tests.items"
_NOW = datetime.now(timezone.utc)


class _FakeTask:
    count_keys = frozenset({"deleted"})
    observation_keys = frozenset({"examined"})
    blocked_keys: frozenset[str] = frozenset()
    name = _TASK

    def __init__(
        self,
        session: AsyncSession,
        extra_steps: tuple[RetentionStep, ...] = (),
        after_batch: Callable[[RetentionBatch], Awaitable[None]] | None = None,
        reported: Callable[[RetentionBatch, RetentionStepResult], RetentionStepResult]
        | None = None,
    ) -> None:
        self.session = session
        self.extra_steps = extra_steps
        self.after_batch = after_batch
        # Replaces what the items step reports after it has deleted.
        self.reported = reported

    def steps(self) -> Sequence[RetentionStep]:
        return (RetentionStep(name="items", run=self._items), *self.extra_steps)

    async def _items(self, batch: RetentionBatch) -> RetentionStepResult:
        ids = list(
            await self.session.scalars(
                sa.select(RetentionJobRuns.id)
                .where(RetentionJobRuns.task == _ITEMS_TASK)
                .order_by(RetentionJobRuns.id)
                .limit(batch.rows)
                .with_for_update()
            )
        )
        await self.session.execute(
            sa.delete(RetentionJobRuns).where(uuid_in(RetentionJobRuns.id, ids))
        )
        if self.after_batch is not None:
            await self.after_batch(batch)
        result = RetentionStepResult(
            rows=len(ids),
            effects=(
                RetentionTenantEffect(tenant_id=None, counts={"deleted": len(ids)}),
            ),
            exhausted=len(ids) < batch.rows,
        )
        return self.reported(batch, result) if self.reported is not None else result


async def _work_items(count: int) -> list[UUID]:
    async with _committed() as session:
        rows = [
            RetentionJobRuns(
                task=_ITEMS_TASK,
                outcome=RetentionJobOutcome.SUCCEEDED.value,
                started_at=_NOW,
                heartbeat_at=_NOW,
                finished_at=_NOW,
            )
            for _ in range(count)
        ]
        session.add_all(rows)
        await session.flush()
        return sorted(row.id for row in rows)


async def _remaining(ids: list[UUID]) -> int:
    async with _committed() as session:
        return int(
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(RetentionJobRuns)
                .where(uuid_in(RetentionJobRuns.id, ids))
            )
            or 0
        )


async def _run(
    *, chunk_rows: int = 500, budget_rows: int = 100_000
) -> RetentionRunReport:
    async with sessionmanager.session() as session:
        return await _runner(
            session, chunk_rows=chunk_rows, budget_rows=budget_rows
        ).run(_FakeTask(session))


@asynccontextmanager
async def _committed() -> AsyncIterator[AsyncSession]:
    async with sessionmanager.session() as session, session.begin():
        yield session


def _runner(
    session: AsyncSession,
    *,
    chunk_rows: int = 500,
    budget_rows: int = 100_000,
    budget_seconds: float = 600,
    lock_timeout_ms: int = 2_000,
    clock: Callable[[], float] | None = None,
) -> RetentionRunner:
    return RetentionRunner(
        session=session,
        job_runs=RetentionJobRunRepository(session),
        audit_service=AuditService(repository=AuditLogRepositoryImpl(session)),
        budget=RetentionBudget(rows=budget_rows, files=100_000, seconds=budget_seconds),
        limits=RetentionChunkLimits(
            rows=chunk_rows,
            statement_timeout_ms=30_000,
            lock_timeout_ms=lock_timeout_ms,
            lease_stale_seconds=3600,
        ),
        **({"clock": clock} if clock is not None else {}),
    )


async def _audits() -> list[AuditLogTable]:
    async with _committed() as session:
        audits = list(
            await session.scalars(
                sa.select(AuditLogTable)
                .where(
                    AuditLogTable.action.in_(
                        [
                            ActionType.DATA_RETENTION_BATCH.value,
                            ActionType.DATA_RETENTION_SKIPPED.value,
                        ]
                    )
                )
                .order_by(AuditLogTable.timestamp)
            )
        )
        session.expunge_all()
        return audits


async def _run_audits() -> list[AuditLogTable]:
    async with _committed() as session:
        audits = list(
            await session.scalars(
                sa.select(AuditLogTable).where(
                    AuditLogTable.action == ActionType.DATA_RETENTION_RUN.value
                )
            )
        )
        session.expunge_all()
        return audits


async def _claim(lease_stale_seconds: int = 3600) -> UUID | None:
    async with _committed() as session:
        return await RetentionJobRunRepository(session).claim(
            task=_TASK, lease_stale_seconds=lease_stale_seconds
        )


async def _until_a_session_waits_on_a_lock() -> None:
    """Proves the concurrent statement reached the database and is blocked."""
    for _ in range(200):
        async with _committed() as session:
            waiting = await session.scalar(
                sa.text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND datname = current_database() "
                    "AND query ILIKE '%retention_job_runs%'"
                )
            )
        if waiting:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the concurrent statement never waited on a lock")


async def _running_rows() -> int:
    async with _committed() as session:
        return int(
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(RetentionJobRuns)
                .where(RetentionJobRuns.outcome == RetentionJobOutcome.RUNNING.value)
            )
            or 0
        )


async def _make_stale(job_run_id: UUID) -> None:
    async with _committed() as session:
        await session.execute(
            sa.update(RetentionJobRuns)
            .where(RetentionJobRuns.id == job_run_id)
            .values(heartbeat_at=sa.func.now() - timedelta(hours=2))
        )


async def test_two_claims_at_once_leave_one_execution() -> None:
    """Kills dropping the unique active-task lease."""
    async with sessionmanager.session() as first:
        async with first.begin():
            first_id = await RetentionJobRunRepository(first).claim(
                task=_TASK, lease_stale_seconds=3600
            )
            second = asyncio.create_task(_claim())
            # The second insert waits on the partial unique index.
            await _until_a_session_waits_on_a_lock()
            assert not second.done()
        assert first_id is not None
    assert await second is None
    assert await _running_rows() == 1


async def test_stale_takeover_fences_the_superseded_execution() -> None:
    """Kills renewing or finishing a superseded execution."""
    stale_id = await _claim()
    assert stale_id is not None
    await _make_stale(stale_id)

    replacement_id = await _claim(lease_stale_seconds=3600)

    assert replacement_id not in (None, stale_id)
    async with _committed() as session:
        repo = RetentionJobRunRepository(session)
        assert await repo.renew(stale_id) is False
        assert (
            await repo.finish(
                stale_id, outcome=RetentionJobOutcome.SUCCEEDED, error_code=None
            )
            is False
        )
        superseded = await session.get(RetentionJobRuns, stale_id)
        assert superseded is not None
        assert superseded.outcome == RetentionJobOutcome.SUPERSEDED.value
    assert await _running_rows() == 1


async def test_renewed_execution_is_not_superseded() -> None:
    """Kills stale takeover without a fresh heartbeat check."""
    owner_id = await _claim()
    assert owner_id is not None
    # A fresh heartbeat is never taken over.
    assert await _claim(lease_stale_seconds=3600) is None
    await _make_stale(owner_id)

    async with sessionmanager.session() as owner:
        async with owner.begin():
            # A chunk's first statement renews and keeps the row locked to commit.
            assert await RetentionJobRunRepository(owner).renew(owner_id)
            takeover = asyncio.create_task(_claim(lease_stale_seconds=3600))
            await _until_a_session_waits_on_a_lock()
            assert not takeover.done()

    assert await takeover is None
    async with _committed() as session:
        owner_row = await session.get(RetentionJobRuns, owner_id)
        assert owner_row is not None
        assert owner_row.outcome == RetentionJobOutcome.RUNNING.value


async def test_a_claim_that_waits_past_the_lock_timeout_records_a_skip() -> None:
    """Kills a claim timeout raised as a crash or returned without a skipped row."""
    async with sessionmanager.session() as holder:
        await holder.begin()
        # An uncommitted running row makes the runner's claim wait on it.
        assert await RetentionJobRunRepository(holder).claim(
            task=_TASK, lease_stale_seconds=3600
        )
        async with sessionmanager.session() as session:
            report = await _runner(session, lock_timeout_ms=100).run(_FakeTask(session))
        await holder.rollback()

    assert (report.outcome, report.error_code) == (
        RetentionJobOutcome.SKIPPED,
        RetentionErrorCode.CLAIM_TIMEOUT,
    )
    async with _committed() as session:
        row = (
            await session.execute(
                sa.select(RetentionJobRuns.outcome, RetentionJobRuns.error_code).where(
                    RetentionJobRuns.id == report.job_run_id
                )
            )
        ).one()
    assert tuple(row) == (
        RetentionJobOutcome.SKIPPED.value,
        RetentionErrorCode.CLAIM_TIMEOUT.value,
    )


async def test_an_outcome_that_waits_past_the_lock_timeout_leaves_the_lease(
    test_tenant,
) -> None:
    """Kills a finish timeout raised as a crash or reported as a final outcome."""
    release = asyncio.Event()
    holders: list[asyncio.Task[None]] = []

    async def hold(job_run_id: UUID) -> None:
        async with _committed() as session:
            await session.execute(
                sa.select(RetentionJobRuns.id)
                .where(RetentionJobRuns.id == job_run_id)
                .with_for_update()
            )
            await release.wait()

    async def lock_after_commit(batch: RetentionBatch) -> None:
        # Queued behind the chunk's renewal, the holder takes the row on commit,
        # before the runner's finish statement reaches it.
        holders.append(asyncio.create_task(hold(batch.job_run_id)))
        await _until_a_session_waits_on_a_lock()

    try:
        async with sessionmanager.session() as session:
            report = await _runner(session, lock_timeout_ms=200).run(
                _FakeTask(session, after_batch=lock_after_commit)
            )
    finally:
        release.set()
        await asyncio.gather(*holders)

    assert (report.outcome, report.error_code) == (
        RetentionJobOutcome.RUNNING,
        RetentionErrorCode.FINISH_TIMEOUT,
    )
    assert await _running_rows() == 1


async def test_audit_failure_rolls_back_the_batch_and_its_progress(
    test_tenant, monkeypatch
) -> None:
    """Kills committing deletion, progress or the final outcome when a required
    audit event fails (the end event written outside the finish transaction)."""
    items = await _work_items(1)

    async def unavailable(self, audit_log):
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(AuditLogRepositoryImpl, "create", unavailable)

    with pytest.raises(RuntimeError):
        await _run()

    assert await _remaining(items) == 1
    async with _committed() as session:
        [job] = await session.scalars(
            sa.select(RetentionJobRuns).where(RetentionJobRuns.task == _TASK)
        )
        # The stale takeover records the execution the finish could not end.
        assert (job.outcome, job.batch_count, job.counts) == (
            RetentionJobOutcome.RUNNING.value,
            0,
            {},
        )


async def test_batch_audit_is_required_even_when_the_action_is_switched_off(
    test_tenant, monkeypatch
) -> None:
    """Kills applying configurable audit suppression to required batches."""
    await _work_items(1)

    async def switched_off(self, tenant_id, action) -> bool:
        return False

    monkeypatch.setattr(AuditService, "_should_log_action", switched_off)

    await _run()

    assert len(await _audits()) == 1


async def test_budget_stops_the_run_and_the_next_run_resumes(test_tenant) -> None:
    """Kills ignoring execution caps, random batch audit ids, or dropping a
    second event with a batch's id instead of failing."""
    items = await _work_items(5)

    first = await _run(chunk_rows=2, budget_rows=3)
    second = await _run(chunk_rows=2, budget_rows=3)

    assert first.outcome == RetentionJobOutcome.PARTIAL
    assert first.counts == {"items.deleted": 3}
    assert second.outcome == RetentionJobOutcome.SUCCEEDED
    assert second.counts == {"items.deleted": 2}
    assert await _remaining(items) == 0
    audits = await _audits()
    # One audit per committed batch that deleted (2 + 1, then 2), its id derived
    # from the batch identity.
    assert len(audits) == 3
    for audit in audits:
        job_run_id = UUID(audit.log_metadata["job_run_id"])
        assert job_run_id in (first.job_run_id, second.job_run_id)
        assert audit.id == retention_batch_audit_id(
            job_run_id=job_run_id,
            batch_seq=audit.log_metadata["batch_seq"],
            tenant_id=test_tenant.id,
        )
    # A second event with a committed batch's id fails its chunk.
    with pytest.raises(IntegrityError):
        async with _committed() as session:
            await AuditService(repository=AuditLogRepositoryImpl(session)).log(
                audit_id=audits[0].id,
                tenant_id=test_tenant.id,
                actor_type=ActorType.SYSTEM,
                action=ActionType.DATA_RETENTION_BATCH,
                entity_type=EntityType.TENANT_SETTINGS,
                entity_id=test_tenant.id,
                description="duplicate",
                metadata={},
                required=True,
            )
    assert len(await _audits()) == 3


async def test_a_stale_takeover_continues_from_the_superseded_cursors() -> None:
    """Kills starting the replacement from an empty cursor."""
    position = RetentionKeyset(at=_NOW, id=uuid4(), group=uuid4())
    stale_id = await _claim()
    assert stale_id is not None
    async with _committed() as session:
        await RetentionJobRunRepository(session).record_progress(
            stale_id, batch_count=1, counts={}, blocked={}, cursors={"scan": position}
        )
    await _make_stale(stale_id)

    replacement_id = await _claim()

    assert replacement_id is not None
    async with _committed() as session:
        cursors = await RetentionJobRunRepository(session).cursors(replacement_id)
    # The superseded execution committed its chunks; their positions hold.
    assert cursors == {"scan": position}


class _OverdueTask(_FakeTask):
    """A fake task that reports overdue work; `snapshot` may raise."""

    def __init__(
        self,
        session: AsyncSession,
        snapshot: Callable[[], Awaitable[RetentionOverdue]],
        extra_steps: tuple[RetentionStep, ...] = (),
        after_batch: Callable[[RetentionBatch], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(session, extra_steps=extra_steps, after_batch=after_batch)
        self._snapshot = snapshot

    async def overdue(self) -> RetentionOverdue:
        return await self._snapshot()


async def _job_row(job_run_id: UUID | None) -> RetentionJobRuns:
    assert job_run_id is not None
    async with _committed() as session:
        row = await session.get(RetentionJobRuns, job_run_id)
        assert row is not None
        session.expunge(row)
        return row


class _Deadlocked(Exception):
    sqlstate = "40P01"


@pytest.mark.parametrize(
    "ending", ["budget", "failed_chunk", "timed_out_chunk", "deadlocked_chunk"]
)
async def test_every_ending_writes_the_overdue_snapshot(test_tenant, ending) -> None:
    """Mutant runner_no_snapshot_on_failure; deadlocked_chunk kills a deadlock
    (a lock cycle with a user transaction) ending the run as failed."""
    await _work_items(3)
    due = datetime(2026, 9, 1, tzinfo=timezone.utc)

    async def snapshot() -> RetentionOverdue:
        return RetentionOverdue(count=7, complete=False, oldest_due_at=due)

    async def fail(batch: RetentionBatch) -> RetentionStepResult:
        raise RuntimeError("a chunk failed")

    async def time_out(batch: RetentionBatch) -> RetentionStepResult:
        await session.execute(sa.text("SET LOCAL statement_timeout = 1"))
        await session.execute(sa.text("SELECT pg_sleep(0.2)"))
        return RetentionStepResult(exhausted=True)

    async def deadlock(batch: RetentionBatch) -> RetentionStepResult:
        raise DBAPIError("DELETE", None, _Deadlocked())

    extra = {
        "budget": (),
        "failed_chunk": (RetentionStep(name="boom", run=fail),),
        "timed_out_chunk": (RetentionStep(name="slow", run=time_out),),
        "deadlocked_chunk": (RetentionStep(name="cycle", run=deadlock),),
    }[ending]
    async with sessionmanager.session() as session:
        task = _OverdueTask(session, snapshot, extra_steps=extra)
        report = await _runner(
            session, chunk_rows=1, budget_rows=1 if ending == "budget" else 100
        ).run(task)

    expected = {
        "budget": (RetentionJobOutcome.PARTIAL, None),
        "failed_chunk": (RetentionJobOutcome.FAILED, RetentionErrorCode.CHUNK_FAILED),
        "timed_out_chunk": (
            RetentionJobOutcome.PARTIAL,
            RetentionErrorCode.CHUNK_TIMEOUT,
        ),
        "deadlocked_chunk": (
            RetentionJobOutcome.PARTIAL,
            RetentionErrorCode.CHUNK_DEADLOCK,
        ),
    }[ending]
    assert (report.outcome, report.error_code) == expected
    row = await _job_row(report.job_run_id)
    assert row.overdue_observed_at is not None
    assert (row.overdue_count, row.overdue_complete) == (7, False)
    assert row.overdue_oldest_due_at == due
    assert row.finished_at is not None and row.overdue_observed_at <= row.finished_at


@pytest.mark.parametrize("budget_rows, first_deleted", [(1, 0), (3, 1)])
async def test_job_history_charges_discovery_and_preserves_live_rows(
    test_tenant, budget_rows, first_deleted
) -> None:
    """Kills uncharged discovery, ignored policy, unbounded prune and live-row deletion."""
    async with _committed() as session:
        session.add(AuditRetentionPolicy(tenant_id=test_tenant.id, retention_days=30))
        expired = [
            RetentionJobRuns(
                task=_ITEMS_TASK,
                outcome=RetentionJobOutcome.SUCCEEDED.value,
                started_at=_NOW - timedelta(days=days),
                heartbeat_at=_NOW - timedelta(days=days),
                finished_at=_NOW - timedelta(days=days),
            )
            for days in (31, 40, 60, 400)
        ]
        live = RetentionJobRuns(
            task="tests.active",
            outcome=RetentionJobOutcome.RUNNING.value,
            started_at=_NOW - timedelta(days=400),
            heartbeat_at=_NOW - timedelta(days=400),
        )
        recent = RetentionJobRuns(
            task=_ITEMS_TASK,
            outcome=RetentionJobOutcome.FAILED.value,
            started_at=_NOW,
            heartbeat_at=_NOW,
            finished_at=_NOW,
        )
        session.add_all([*expired, live, recent])
        await session.flush()
        expired_ids = [row.id for row in expired]
        retained_ids = [live.id, recent.id]

    async with sessionmanager.session() as session:
        first = await _runner(session, budget_rows=budget_rows).run(
            JobHistoryRetentionTask(session)
        )
    assert first.outcome is RetentionJobOutcome.PARTIAL
    assert first.counts.get("history.job_runs_examined", 0) == first_deleted
    assert first.counts.get("history.job_runs_deleted", 0) == first_deleted
    assert await _remaining(expired_ids) == 4 - first_deleted
    assert await _remaining(retained_ids) == 2

    async with sessionmanager.session() as session:
        resumed = await _runner(session).run(JobHistoryRetentionTask(session))
    assert resumed.outcome is RetentionJobOutcome.SUCCEEDED
    assert resumed.counts == {
        "history.job_runs_examined": 4 - first_deleted,
        "history.job_runs_deleted": 4 - first_deleted,
    }
    assert await _remaining(expired_ids) == 0
    assert await _remaining(retained_ids) == 2
    audits = await _audits()
    assert sum(a.log_metadata["counts"].get("job_runs_deleted", 0) for a in audits) == 4


_OK = RetentionJobOutcome.SUCCEEDED
_RUNNING = RetentionJobOutcome.RUNNING
_SKIPPED = RetentionJobOutcome.SKIPPED
_OFF = RetentionErrorCode.DISABLED_BY_DEPLOYMENT_SETTING


async def _no_overdue() -> RetentionOverdue:
    return RetentionOverdue(count=0, complete=True)


# age: days since the latest row started and last renewed its heartbeat.
@pytest.mark.parametrize(
    "age, outcome, error, snapshot, enabled, reports, expected, flags, sibling_ran",
    [
        (None, None, None, None, True, True, "initializing", {"no_execution"}, False),
        # The scheduled run reached the sibling, so this task's claim raised.
        (None, None, None, None, True, True, "unknown", {"no_execution"}, True),
        # No row yet: the API's own setting is the only evidence.
        (
            None,
            None,
            None,
            None,
            False,
            True,
            "degraded",
            {"disabled", "no_execution"},
            False,
        ),
        # The worker skipped it, whatever the API process's setting says.
        (0, _SKIPPED, _OFF, None, True, False, "degraded", {"disabled"}, False),
        # The worker ran it although the API process has it turned off.
        (0, _OK, None, None, False, False, "healthy", set(), False),
        (0, _OK, None, None, True, False, "healthy", set(), False),
        (
            0,
            _RUNNING,
            None,
            None,
            True,
            True,
            "initializing",
            {"no_overdue_snapshot"},
            False,
        ),
        # A crashed worker: its running row stopped renewing hours ago.
        (0.5, _RUNNING, None, None, True, False, "unknown", {"abandoned"}, False),
        (0, _OK, None, None, True, True, "unknown", {"no_overdue_snapshot"}, False),
        (3, _OK, None, (0, 0, True), True, True, "degraded", {"stale"}, False),
        (0, _OK, None, (0, 7, False), True, True, "degraded", {"overdue"}, False),
        (
            0,
            _OK,
            None,
            (3, 0, True),
            True,
            True,
            "unknown",
            {"overdue_snapshot_stale"},
            False,
        ),
        (0, _OK, None, (0, 0, True), True, True, "healthy", set(), False),
        (0, _OK, None, (0, 0, False), True, True, "unknown", set(), False),
        (
            0,
            RetentionJobOutcome.FAILED,
            RetentionErrorCode.CHUNK_FAILED,
            (0, 0, True),
            True,
            True,
            "degraded",
            {"failed"},
            False,
        ),
        (
            0,
            _SKIPPED,
            RetentionErrorCode.CLAIM_TIMEOUT,
            None,
            True,
            False,
            "unknown",
            set(),
            False,
        ),
        (
            0,
            RetentionJobOutcome.SUPERSEDED,
            None,
            None,
            True,
            False,
            "unknown",
            set(),
            False,
        ),
    ],
    ids=[
        "never-run",
        "never-run-beside-a-run",
        "disabled-before-a-row",
        "disabled-by-the-worker",
        "enabled-in-the-worker",
        "no-reporter",
        "first-running",
        "abandoned",
        "missing-snapshot",
        "stale-job",
        "overdue-lower-bound",
        "stale-snapshot",
        "empty-complete",
        "empty-incomplete",
        "failed",
        "claim-timeout",
        "superseded",
    ],
)
async def test_retention_health_reports_observation_gaps(
    age, outcome, error, snapshot, enabled, reports, expected, flags, sibling_ran
) -> None:
    """Kills healthy-on-missing/stale/incomplete evidence, ignored disabled/overdue
    flags, a fresh failed, superseded or unclaimed run reading healthy, a task
    that never ran beside one that did staying initializing, an abandoned
    running row reading healthy, `disabled` read from the API process's
    setting instead of the worker's latest row, and `no_execution` dropped for
    a disabled task without a row."""
    if sibling_ran:
        async with _committed() as session:
            session.add(
                RetentionJobRuns(
                    task=_ITEMS_TASK,
                    outcome=_OK.value,
                    started_at=_NOW,
                    heartbeat_at=_NOW,
                    finished_at=_NOW,
                )
            )
    if age is not None:
        at = _NOW - timedelta(days=age)
        async with _committed() as session:
            row = RetentionJobRuns(
                task=_TASK,
                outcome=outcome.value,
                started_at=at,
                heartbeat_at=at,
                finished_at=None if outcome is _RUNNING else at,
                error_code=error.value if error is not None else None,
                counts={"items.deleted": 4},
                blocked={"items.held": 1, "items.locked": 0},
            )
            if snapshot is not None:
                observed_age, count, complete = snapshot
                row.overdue_observed_at = _NOW - timedelta(days=observed_age)
                row.overdue_count = count
                row.overdue_complete = complete
                row.overdue_oldest_due_at = _NOW - timedelta(days=5) if count else None
            session.add(row)

    def build(session: AsyncSession) -> _FakeTask:
        return _OverdueTask(session, _no_overdue) if reports else _FakeTask(session)

    config = RetentionTaskRegistration(
        name=_TASK,
        enabled=enabled,
        budget=RetentionBudget(rows=10, files=10, seconds=10),
        build=build,
    )
    sibling = RetentionTaskRegistration(
        name=_ITEMS_TASK,
        enabled=True,
        budget=config.budget,
        build=_FakeTask,
    )
    async with _committed() as session:
        health = await load_retention_health(
            RetentionJobRunRepository(session),
            (config, sibling) if sibling_ran else (config,),
            now=_NOW,
            lease_stale_after=timedelta(hours=1),
        )
    assert health.status is RetentionHealthStatus(expected)
    assert len(health.tasks) == (2 if sibling_ran else 1)
    task = health.tasks[0]
    assert task.name == _TASK and task.status == health.status
    assert {
        flag
        for flag in (
            "disabled",
            "stale",
            "overdue",
            "no_execution",
            "no_overdue_snapshot",
            "overdue_snapshot_stale",
            "abandoned",
            "failed",
        )
        if getattr(task, flag)
    } == flags
    if age is not None:
        assert (task.latest_outcome, task.error_code) == (outcome, error)
        assert task.blocked_reasons == ("items.held",)
    if snapshot is not None:
        assert task.overdue_complete == snapshot[2]


async def test_one_raising_task_does_not_stop_the_others(test_tenant) -> None:
    """Kills one task's error (here a failing claim) aborting the nightly run."""
    items = await _work_items(2)

    class _Unclaimable(_FakeTask):
        # Outside the task name pattern: the claim's insert fails its CHECK.
        name = "tests.Unclaimable"

    budget = RetentionBudget(rows=100, files=100, seconds=60)
    async with sessionmanager.session() as session:
        reports = await run_registered_tasks(
            session,
            tuple(
                RetentionTaskRegistration(
                    name=task.name, enabled=True, budget=budget, build=task
                )
                for task in (_Unclaimable, _FakeTask)
            ),
            lambda _: _runner(session),
        )

    assert [(report.task, report.outcome) for report in reports] == [
        (_TASK, RetentionJobOutcome.SUCCEEDED)
    ]
    assert await _remaining(items) == 0


@pytest.mark.parametrize("breach", ["over_charge", "undeclared_key"])
async def test_a_step_breaking_its_contract_fails_and_commits_nothing(
    test_tenant, breach
) -> None:
    """Kills dropping the batch-charge check (over_charge) or the closed-set check
    of count keys (undeclared_key), or recording an adopter's contract breach as
    a database failure (chunk_failed)."""
    items = await _work_items(1)

    def broken(
        batch: RetentionBatch, result: RetentionStepResult
    ) -> RetentionStepResult:
        if breach == "over_charge":
            return replace(result, rows=batch.rows + 1)
        undeclared = RetentionTenantEffect(tenant_id=None, counts={"undeclared": 1})
        return replace(result, effects=(undeclared,))

    async with sessionmanager.session() as session:
        report = await _runner(session).run(_FakeTask(session, reported=broken))

    assert (report.outcome, report.error_code) == (
        RetentionJobOutcome.FAILED,
        RetentionErrorCode.CONTRACT_VIOLATION,
    )
    assert await _remaining(items) == 1
    row = await _job_row(report.job_run_id)
    assert (row.batch_count, row.counts) == (0, {})
    assert await _audits() == []


async def test_a_skip_records_its_row_and_a_required_audit(
    test_tenant, monkeypatch
) -> None:
    """Kills a suppressed run without its skipped row, or without its audit event
    when the audit configuration switches the action off."""

    async def switched_off(self, tenant_id, action) -> bool:
        return False

    monkeypatch.setattr(AuditService, "_should_log_action", switched_off)

    async with sessionmanager.session() as session:
        report = await _runner(session).skip(_TASK)

    row = await _job_row(report.job_run_id)
    assert (row.outcome, row.error_code) == (
        RetentionJobOutcome.SKIPPED.value,
        RetentionErrorCode.DISABLED_BY_DEPLOYMENT_SETTING.value,
    )
    [audit] = await _audits()
    assert audit.action == ActionType.DATA_RETENTION_SKIPPED.value
    assert audit.log_metadata["job_run_id"] == str(report.job_run_id)


@pytest.mark.parametrize("kind", ["observed", "disposed", "deferred"])
async def test_observations_are_progress_and_only_disposals_are_audited(
    test_tenant, kind
) -> None:
    """Kills auditing a chunk that only observed or deferred, putting
    observations in a chunk's or the end event, a chunk description without
    its counts, dropping observations from the job row, or recording a
    deferral as a blocked reason instead of a count."""
    counts = {"examined": 5, **({"deleted": 1} if kind == "disposed" else {})}

    def observed(
        batch: RetentionBatch, result: RetentionStepResult
    ) -> RetentionStepResult:
        effect = RetentionTenantEffect(tenant_id=None, counts=counts)
        deferred = kind == "deferred"
        return replace(
            result, rows=5, effects=(effect,), exhausted=not deferred, deferred=deferred
        )

    async with sessionmanager.session() as session:
        report = await _runner(session).run(_FakeTask(session, reported=observed))

    row = await _job_row(report.job_run_id)
    assert row.counts == {
        **{f"items.{key}": value for key, value in counts.items()},
        **({"items.deferred": 1} if kind == "deferred" else {}),
    }
    assert row.blocked == {}
    assert [
        (audit.description, audit.log_metadata["counts"]) for audit in await _audits()
    ] == (
        [("Retention tests.fake, step items: deleted 1", {"deleted": 1})]
        if kind == "disposed"
        else []
    )
    # The end event's totals hold disposal facts only.
    [run] = await _run_audits()
    assert run.log_metadata["counts"] == (
        {"items.deleted": 1} if kind == "disposed" else {}
    )


async def test_the_batch_carries_the_execution_deadline() -> None:
    """Kills a deadline taken from the clock at the chunk, not at the start of
    the execution, which gives the time already spent back to the step."""
    ticks = [100.0, 130.0]
    seen: list[float] = []

    def clock() -> float:
        return ticks.pop(0) if len(ticks) > 1 else ticks[0]

    async def record(batch: RetentionBatch) -> None:
        seen.append(batch.deadline)

    async with sessionmanager.session() as session:
        await _runner(session, budget_seconds=600, clock=clock).run(
            _FakeTask(session, after_batch=record)
        )

    assert seen == [100.0 + 600.0]


@pytest.mark.parametrize("ending", ["finished", "superseded"])
async def test_the_execution_ends_with_one_audit_event_in_its_finish(
    test_tenant, ending
) -> None:
    """Kills dropping the end-of-execution event or writing it for an execution
    that was superseded before it finished."""
    await _work_items(3)
    seen: list[UUID] = []

    async def remember(batch: RetentionBatch) -> None:
        seen.append(batch.job_run_id)

    async def taken_over() -> RetentionOverdue:
        # Another worker takes the stale task over before this one finishes.
        await _make_stale(seen[0])
        assert await _claim() is not None
        return RetentionOverdue(count=0, complete=True)

    async with sessionmanager.session() as session:
        task = (
            _OverdueTask(session, taken_over, after_batch=remember)
            if ending == "superseded"
            else _FakeTask(session, after_batch=remember)
        )
        report = await _runner(session, chunk_rows=1, budget_rows=2).run(task)

    events = await _run_audits()
    if ending == "superseded":
        assert report.outcome is RetentionJobOutcome.SUPERSEDED
        assert events == []
        return
    [event] = events
    assert event.id == retention_run_audit_id(report.job_run_id)
    assert event.tenant_id == test_tenant.id
    assert event.log_metadata == {
        "task": _TASK,
        "job_run_id": str(report.job_run_id),
        "outcome": "partial",
        "error_code": None,
        "counts": {"items.deleted": 2},
        "blocked": {},
        "batch_count": 2,
    }
    assert event.description == ("Retention tests.fake finished: partial; deleted 2")
