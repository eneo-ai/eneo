"""The five-minute retention run: frequent tasks run only when something is due.

The work items are completed job rows of their own task names, so no product
schema takes part; each fake task removes its items and asks whether one is
due at its time.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.audit.application.audit_service import AuditService
from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from eneo.data_retention.application.retention_health import (
    RetentionHealth,
    RetentionHealthStatus,
)
from eneo.data_retention.application.retention_registration import (
    RetentionTaskRegistration,
)
from eneo.data_retention.application.retention_runner import (
    RetentionBatch,
    RetentionChunkLimits,
    RetentionRunner,
    RetentionStep,
    RetentionStepResult,
    RetentionTenantEffect,
)
from eneo.data_retention.domain.retention import (
    RetentionBudget,
    RetentionErrorCode,
    RetentionJobOutcome,
)
from eneo.data_retention.infrastructure import retention_worker
from eneo.data_retention.infrastructure.retention_job_run_repo import (
    RetentionJobRunRepository,
)
from eneo.data_retention.infrastructure.retention_sql import uuid_in
from eneo.data_retention.infrastructure.retention_worker import (
    run_due_tasks,
    run_registered_tasks,
)
from eneo.database.database import sessionmanager
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.retention_tables import RetentionJobRuns
from eneo.main import retention_tasks
from eneo.main.config import Settings, get_settings

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# A frequent task's items fall due this long after they finished.
_AFTER = timedelta(hours=1)


@asynccontextmanager
async def _committed() -> AsyncIterator[AsyncSession]:
    async with sessionmanager.session() as session, session.begin():
        yield session


async def _database_now() -> datetime:
    async with _committed() as session:
        return (await session.execute(sa.select(sa.func.now()))).scalar_one()


async def _items(owner: str, count: int, *, finished: datetime) -> None:
    async with _committed() as session:
        session.add_all(
            RetentionJobRuns(
                task=f"{owner}_items",
                outcome=RetentionJobOutcome.SUCCEEDED.value,
                started_at=finished,
                heartbeat_at=finished,
                finished_at=finished,
            )
            for _ in range(count)
        )


async def _left(owner: str) -> int:
    async with _committed() as session:
        return (
            await session.scalar(
                sa.select(sa.func.count()).where(
                    RetentionJobRuns.task == f"{owner}_items"
                )
            )
            or 0
        )


async def _job_rows(*tasks: str) -> list[tuple[str, str]]:
    async with _committed() as session:
        return [
            (task, outcome)
            for task, outcome in await session.execute(
                sa.select(RetentionJobRuns.task, RetentionJobRuns.outcome)
                .where(RetentionJobRuns.task.in_(tasks))
                .order_by(RetentionJobRuns.started_at)
            )
        ]


async def _retention_audits() -> int:
    async with _committed() as session:
        return (
            await session.scalar(
                sa.select(sa.func.count()).where(
                    AuditLog.action.in_(
                        [
                            "data_retention_batch",
                            "data_retention_run",
                            "data_retention_skipped",
                        ]
                    )
                )
            )
            or 0
        )


class _DueItems:
    """Removes its items one per chunk once they are due at `now`."""

    count_keys = frozenset({"deleted"})
    observation_keys: frozenset[str] = frozenset()
    blocked_keys: frozenset[str] = frozenset()
    not_due_keys: frozenset[str] = frozenset()

    def __init__(
        self,
        session: AsyncSession,
        name: str,
        *,
        now: datetime,
        chunk: Callable[[], None] | None = None,
        probe: Callable[[], None] | None = None,
    ) -> None:
        self.session = session
        self.name = name
        self.now = now
        self.chunk = chunk
        self.probe = probe

    def _due(self) -> sa.ColumnElement[bool]:
        return sa.and_(
            RetentionJobRuns.task == f"{self.name}_items",
            RetentionJobRuns.finished_at <= self.now - _AFTER,
        )

    async def has_due(self) -> bool:
        if self.probe is not None:
            self.probe()
        return bool(
            await self.session.scalar(sa.select(sa.exists().where(self._due())))
        )

    def steps(self) -> Sequence[RetentionStep]:
        return (RetentionStep(name="items", run=self._remove),)

    async def _remove(self, batch: RetentionBatch) -> RetentionStepResult:
        if self.chunk is not None:
            self.chunk()
        ids: list[UUID] = list(
            await self.session.scalars(
                sa.select(RetentionJobRuns.id)
                .where(self._due())
                .limit(batch.rows)
                .with_for_update()
            )
        )
        await self.session.execute(
            sa.delete(RetentionJobRuns).where(uuid_in(RetentionJobRuns.id, ids))
        )
        return RetentionStepResult(
            rows=len(ids),
            effects=(
                RetentionTenantEffect(tenant_id=None, counts={"deleted": len(ids)}),
            ),
            exhausted=len(ids) < batch.rows,
        )


def _frequent(
    name: str,
    build: Callable[[AsyncSession], _DueItems],
    *,
    enabled: bool = True,
) -> RetentionTaskRegistration:
    [paced] = retention_tasks._paced(
        [
            RetentionTaskRegistration(
                name=name,
                enabled=enabled,
                budget=RetentionBudget(rows=1000, files=1000, seconds=1800),
                build=build,
                every="frequent",
            )
        ]
    )
    return paced


def _runner_for(
    session: AsyncSession, clock: Callable[[], float] | None = None
) -> Callable[[RetentionBudget], RetentionRunner]:
    def runner(budget: RetentionBudget) -> RetentionRunner:
        made = RetentionRunner(
            session=session,
            job_runs=RetentionJobRunRepository(session),
            audit_service=AuditService(repository=AuditLogRepositoryImpl(session)),
            budget=budget,
            limits=RetentionChunkLimits(
                rows=1,
                statement_timeout_ms=30_000,
                lock_timeout_ms=2_000,
                lease_stale_seconds=3600,
            ),
        )
        if clock is not None:
            made.clock = clock
        return made

    return runner


def _raises(*_: object) -> _DueItems:
    raise AssertionError("A disabled frequent task was built.")


async def test_nothing_due_claims_nothing_and_writes_nothing(test_tenant) -> None:
    """Mutant: the frequent run claims its task before asking whether anything
    is due, so every tick writes a job row and an audit event."""
    now = await _database_now()
    await _items("tests.quiet", 1, finished=now - _AFTER + timedelta(minutes=5))

    async with sessionmanager.session() as session:
        reports = await run_due_tasks(
            session,
            [_frequent("tests.quiet", lambda s: _DueItems(s, "tests.quiet", now=now))],
            _runner_for(session),
        )

    assert reports == []
    assert await _job_rows("tests.quiet") == []
    assert await _retention_audits() == 0
    assert await _left("tests.quiet") == 1


async def test_a_disabled_frequent_task_is_left_to_the_nightly_run(
    test_tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With due work and its switch off, the five-minute cron builds nothing,
    asks no probe and writes no row, skip row or audit event; the nightly run
    records the skip once a day.

    Mutant: the frequent cron records a skip on every tick."""
    now = await _database_now()
    await _items("tests.off", 1, finished=now - 2 * _AFTER)

    def registrations(
        settings: Settings, *, now: datetime | None = None
    ) -> tuple[RetentionTaskRegistration, ...]:
        return (_frequent("tests.off", _raises, enabled=False),)

    monkeypatch.setattr(retention_worker, "retention_task_registrations", registrations)
    reports = await _frequent_cron()

    assert reports == []
    assert await _job_rows("tests.off") == []
    assert await _retention_audits() == 0
    assert await _left("tests.off") == 1


async def _frequent_cron() -> list[object]:
    """Run the general worker's five-minute cron as ARQ calls it."""
    from eneo.worker.arq import worker

    [cron] = [
        job
        for job in worker.cron_jobs
        if job.coroutine.__name__ == "run_retention_frequent"
    ]
    return await cron.coroutine({})


async def test_without_frequent_tasks_the_cron_takes_no_connection(
    setup_database,
) -> None:
    """Develop registers no frequent task: every five minutes the cron starts,
    finds none and ends before it touches the database.

    Mutant: the cron reads the database clock before it knows it has work."""
    from eneo.worker.arq import worker

    [cron] = [
        job
        for job in worker.cron_jobs
        if job.coroutine.__name__ == "run_retention_frequent"
    ]
    assert cron.minute == set(range(0, 60, 5))

    checkouts: list[object] = []
    pool = sessionmanager._engine.sync_engine.pool  # type: ignore[union-attr]

    def checked_out(*args: object) -> None:
        checkouts.append(args)

    sa.event.listen(pool, "checkout", checked_out)
    try:
        assert await _frequent_cron() == []
    finally:
        sa.event.remove(pool, "checkout", checked_out)
    assert checkouts == []


async def test_a_due_item_is_removed_by_the_first_tick_after_its_time(
    test_tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tick reads the database's clock once at its start and builds the
    task with it.

    Mutants: the tick takes the worker's clock; the tick removes an item
    before its time."""
    now = await _database_now()
    await _items("tests.soon", 1, finished=now - _AFTER + timedelta(minutes=10))

    def registrations(
        settings: Settings, *, now: datetime | None = None
    ) -> tuple[RetentionTaskRegistration, ...]:
        assert now is None or now.tzinfo is not None
        return (
            _frequent(
                "tests.soon",
                lambda session: _DueItems(
                    session, "tests.soon", now=now or datetime(2000, 1, 1)
                ),
            ),
        )

    monkeypatch.setattr(retention_worker, "retention_task_registrations", registrations)
    assert await _frequent_cron() == []
    assert await _left("tests.soon") == 1
    assert await _job_rows("tests.soon") == []

    async with _committed() as session:
        await session.execute(
            sa.update(RetentionJobRuns)
            .where(RetentionJobRuns.task == "tests.soon_items")
            .values(finished_at=now - _AFTER - timedelta(minutes=1))
        )
    [report] = await _frequent_cron()

    assert report.outcome is RetentionJobOutcome.SUCCEEDED  # type: ignore[attr-defined]
    assert await _left("tests.soon") == 0
    assert await _job_rows("tests.soon") == [("tests.soon", "succeeded")]


async def test_a_failing_probe_is_rolled_back_and_the_task_still_runs(
    test_tenant,
) -> None:
    """A broken probe must not stop removal quietly: its transaction is rolled
    back before any claim, the task runs and writes its row, and the next task
    is reached.

    Mutants: the error aborts the session, so the claim fails; the error stops
    the run; the task is skipped."""
    now = await _database_now()
    for owner in ("tests.broken", "tests.after"):
        await _items(owner, 1, finished=now - 2 * _AFTER)

    class _Broken(_DueItems):
        async def has_due(self) -> bool:
            await self.session.execute(sa.text("SELECT 1 / 0"))
            return False

    async with sessionmanager.session() as session:
        reports = await run_due_tasks(
            session,
            [
                _frequent(
                    "tests.broken", lambda s: _Broken(s, "tests.broken", now=now)
                ),
                _frequent(
                    "tests.after", lambda s: _DueItems(s, "tests.after", now=now)
                ),
            ],
            _runner_for(session),
        )

    assert [(report.task, report.outcome) for report in reports] == [
        ("tests.broken", RetentionJobOutcome.SUCCEEDED),
        ("tests.after", RetentionJobOutcome.SUCCEEDED),
    ]
    assert (await _left("tests.broken"), await _left("tests.after")) == (0, 0)


async def test_frequent_tasks_run_in_order_and_each_pass_stops_at_its_limit(
    test_tenant,
) -> None:
    """A never finishes and spends 60 seconds per chunk; C has one due item.

    Mutants: the time limit is checked only at the start of a pass, so A runs
    to its end; a frequent pass keeps the shared 1800 seconds; the tasks run
    out of order."""
    now = await _database_now()
    await _items("tests.a", 10, finished=now - 2 * _AFTER)
    await _items("tests.c", 1, finished=now - 2 * _AFTER)
    clock = [0.0]
    claimed_at: list[float] = []

    def spend() -> None:
        clock[0] += 60

    async with sessionmanager.session() as session:
        reports = await run_due_tasks(
            session,
            [
                _frequent(
                    "tests.a", lambda s: _DueItems(s, "tests.a", now=now, chunk=spend)
                ),
                _frequent("tests.b", lambda s: _DueItems(s, "tests.b", now=now)),
                _frequent(
                    "tests.c",
                    lambda s: _DueItems(
                        s,
                        "tests.c",
                        now=now,
                        chunk=lambda: claimed_at.append(clock[0]),
                    ),
                ),
            ],
            _runner_for(session, clock=lambda: clock[0]),
        )

    assert [(report.task, report.outcome) for report in reports] == [
        ("tests.a", RetentionJobOutcome.PARTIAL),
        ("tests.c", RetentionJobOutcome.SUCCEEDED),
    ]
    assert await _left("tests.a") == 6
    assert claimed_at and claimed_at[0] >= 240
    assert await _left("tests.c") == 0


async def test_a_held_lease_loses_one_claim_and_the_others_still_run(
    test_tenant,
) -> None:
    """A running row with a fresh heartbeat stands in for a slow earlier tick.

    Mutant: the run stops at the first lost claim."""
    now = await _database_now()
    for owner in ("tests.a", "tests.b", "tests.c"):
        await _items(owner, 1, finished=now - 2 * _AFTER)
    async with _committed() as session:
        session.add(
            RetentionJobRuns(
                task="tests.a",
                outcome=RetentionJobOutcome.RUNNING.value,
                started_at=now,
                heartbeat_at=sa.func.clock_timestamp(),
            )
        )

    async with sessionmanager.session() as session:
        reports = await run_due_tasks(
            session,
            [
                _frequent(owner, lambda s, owner=owner: _DueItems(s, owner, now=now))
                for owner in ("tests.a", "tests.b", "tests.c")
            ],
            _runner_for(session),
        )

    assert [(report.task, report.outcome) for report in reports] == [
        ("tests.a", None),
        ("tests.b", RetentionJobOutcome.SUCCEEDED),
        ("tests.c", RetentionJobOutcome.SUCCEEDED),
    ]
    assert await _job_rows("tests.a") == [("tests.a", "running")]
    assert await _left("tests.a") == 1


async def test_overlapping_ticks_never_run_the_same_task_at_once(test_tenant) -> None:
    """Two ticks that overlap both find work; the lease lets only one claim.
    The later tick meets the earlier one inside a chunk, waits on its lock and
    leaves the task to it without a row.

    Mutants: a tick claims a task another tick is still running; the later
    tick records a claim timeout every five minutes."""
    now = await _database_now()
    await _items("tests.slow", 2, finished=now - 2 * _AFTER)
    inside = asyncio.Event()
    release = asyncio.Event()
    running = [0]
    most = [0]

    async def tick() -> list[object]:
        async def hold(batch: RetentionBatch) -> None:
            running[0] += 1
            most[0] = max(most[0], running[0])
            inside.set()
            await release.wait()
            running[0] -= 1

        class _Slow(_DueItems):
            async def _remove(self, batch: RetentionBatch) -> RetentionStepResult:
                await hold(batch)
                return await super()._remove(batch)

        async with sessionmanager.session() as session:
            return list(
                await run_due_tasks(
                    session,
                    [
                        _frequent(
                            "tests.slow", lambda s: _Slow(s, "tests.slow", now=now)
                        )
                    ],
                    _runner_for(session),
                )
            )

    first = asyncio.create_task(tick())
    await inside.wait()
    second = await tick()
    release.set()
    first_reports = await first

    assert [(r.task, r.outcome) for r in second] == [("tests.slow", None)]  # type: ignore[attr-defined]
    assert [(r.task, r.outcome) for r in first_reports] == [  # type: ignore[attr-defined]
        ("tests.slow", RetentionJobOutcome.SUCCEEDED)
    ]
    assert most[0] == 1
    assert await _job_rows("tests.slow") == [("tests.slow", "succeeded")]


async def test_the_nightly_run_runs_a_frequent_task_without_its_probe(
    test_tenant,
) -> None:
    """Every task runs in the nightly run, frequent ones included, and that
    run asks no probe: it writes a row a day, keeps the stale rule meaningful
    and records the skip of one that is turned off.

    Mutant: the nightly run leaves frequent tasks out, or asks their probe."""
    now = await _database_now()
    await _items("tests.nightly", 1, finished=now - 2 * _AFTER)

    def unasked() -> None:
        raise AssertionError("The nightly run asked the probe.")

    async with sessionmanager.session() as session:
        reports = await run_registered_tasks(
            session,
            [
                _frequent(
                    "tests.nightly",
                    lambda s: _DueItems(s, "tests.nightly", now=now, probe=unasked),
                ),
                _frequent("tests.nightly_off", _raises, enabled=False),
            ],
            _runner_for(session),
        )

    assert [(report.task, report.outcome) for report in reports] == [
        ("tests.nightly", RetentionJobOutcome.SUCCEEDED),
        ("tests.nightly_off", RetentionJobOutcome.SKIPPED),
    ]
    assert await _left("tests.nightly") == 0


def _health_of(
    monkeypatch: pytest.MonkeyPatch,
    build: Callable[[AsyncSession, datetime], _DueItems],
    *,
    enabled: bool = True,
) -> None:
    """Health reads one frequent task, built with the time health passes."""

    def registrations(
        settings: Settings, *, now: datetime | None = None
    ) -> tuple[RetentionTaskRegistration, ...]:
        assert now is not None, "health builds its tasks with the database clock"
        return (_frequent("tests.health", lambda s: build(s, now), enabled=enabled),)

    monkeypatch.setattr(retention_tasks, "retention_task_registrations", registrations)


async def _health() -> RetentionHealth:
    return await retention_tasks._read_retention_health(get_settings())


@pytest.mark.parametrize(
    "late,expected",
    [
        (None, RetentionHealthStatus.HEALTHY),
        (timedelta(minutes=30), RetentionHealthStatus.HEALTHY),
        (timedelta(minutes=70), RetentionHealthStatus.DEGRADED),
    ],
    ids=["nothing-due", "due-within-the-hour", "overdue"],
)
async def test_a_frequent_task_reads_overdue_an_hour_past_its_time(
    test_tenant,
    monkeypatch: pytest.MonkeyPatch,
    late: timedelta | None,
    expected: RetentionHealthStatus,
) -> None:
    """A frequent task has no overdue snapshot; health asks its probe an hour
    back on the database clock. With nothing overdue and no job row yet it
    reads healthy (a task that never had anything due is not initializing).

    Mutants: health asks the probe at the present time, so an item a minute
    past its time degrades health; no job row reads initializing or unknown;
    an item more than an hour past its time reads healthy."""
    if late is not None:
        now = await _database_now()
        await _items("tests.health", 1, finished=now - _AFTER - late)
    _health_of(monkeypatch, lambda s, at: _DueItems(s, "tests.health", now=at))

    health = await _health()

    [task] = health.tasks
    assert (health.status, task.status) == (expected, expected)
    assert task.overdue is (expected is RetentionHealthStatus.DEGRADED)
    assert task.no_execution


async def test_a_claim_timeout_with_nothing_overdue_reads_healthy(
    test_tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The nightly run writes a claim timeout row when a tick's chunk holds
    the task; for a frequent task the probe, not that row, says whether work
    is overdue.

    Mutant: a claim timeout reads unknown also when the probe answers, so a
    frequent task reads unknown until something next falls due."""
    now = await _database_now()
    async with _committed() as session:
        session.add(
            RetentionJobRuns(
                task="tests.health",
                outcome=RetentionJobOutcome.SKIPPED.value,
                started_at=now,
                heartbeat_at=now,
                finished_at=now,
                error_code=RetentionErrorCode.CLAIM_TIMEOUT.value,
            )
        )
    _health_of(monkeypatch, lambda s, at: _DueItems(s, "tests.health", now=at))

    [task] = (await _health()).tasks

    assert (task.status, task.error_code) == (
        RetentionHealthStatus.HEALTHY,
        RetentionErrorCode.CLAIM_TIMEOUT,
    )


async def test_a_failed_frequent_run_degrades_health(
    test_tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: a frequent task's health asks only its probe and misses that
    its latest run failed."""
    now = await _database_now()
    async with _committed() as session:
        session.add(
            RetentionJobRuns(
                task="tests.health",
                outcome=RetentionJobOutcome.FAILED.value,
                started_at=now,
                heartbeat_at=now,
                finished_at=now,
                error_code="chunk_failed",
            )
        )
    _health_of(monkeypatch, lambda s, at: _DueItems(s, "tests.health", now=at))

    [task] = (await _health()).tasks

    assert (task.status, task.failed) == (RetentionHealthStatus.DEGRADED, True)


async def test_a_failing_probe_reads_unknown(
    test_tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: a probe that fails reads healthy."""

    class _Broken(_DueItems):
        async def has_due(self) -> bool:
            await self.session.execute(sa.text("SELECT 1 / 0"))
            return False

    _health_of(monkeypatch, lambda s, at: _Broken(s, "tests.health", now=at))

    assert (await _health()).status is RetentionHealthStatus.UNKNOWN


async def _sql_error(session: AsyncSession) -> None:
    await session.execute(sa.text("SELECT 1 / 0"))


async def _os_error(session: AsyncSession) -> None:
    raise OSError("probe could not reach its store")


async def _runtime_error(session: AsyncSession) -> None:
    raise RuntimeError("probe is broken")


async def _slow(session: AsyncSession) -> None:
    # Longer than the whole health read's time limit (one second).
    await session.execute(sa.text("SELECT pg_sleep(2)"))


@pytest.mark.parametrize(
    "fail",
    [_sql_error, _os_error, _runtime_error, _slow],
    ids=["sql-error", "os-error", "runtime-error", "statement-timeout"],
)
async def test_a_failing_probe_leaves_the_other_tasks_health_readable(
    test_tenant,
    monkeypatch: pytest.MonkeyPatch,
    fail: Callable[[AsyncSession], Awaitable[None]],
) -> None:
    """A probe's error, of any kind, is its own task's: that task reads
    unknown and the next task's overdue work still degrades the block. A slow
    probe meets the statement timeout, which ends before the read's own time
    limit and leaves the next task the time to read.

    Mutants: an error escapes, so the whole block reads unknown and hides the
    other task's degraded, or the public read raises; the error aborts the
    shared transaction, so the next task's reads fail; the failing task reads
    healthy; the statement timeout is as long as the read's time limit, so
    the read is cancelled before the probe's statement ends."""

    class _Broken(_DueItems):
        async def has_due(self) -> bool:
            await fail(self.session)
            return False

    now = await _database_now()
    await _items("tests.late", 1, finished=now - _AFTER - timedelta(minutes=70))

    def registrations(
        settings: Settings, *, now: datetime | None = None
    ) -> tuple[RetentionTaskRegistration, ...]:
        assert now is not None
        return (
            _frequent("tests.broken", lambda s: _Broken(s, "tests.broken", now=now)),
            _frequent("tests.late", lambda s: _DueItems(s, "tests.late", now=now)),
        )

    monkeypatch.setattr(retention_tasks, "retention_task_registrations", registrations)

    health = await _health()

    assert [(task.name, task.status) for task in health.tasks] == [
        ("tests.broken", RetentionHealthStatus.UNKNOWN),
        ("tests.late", RetentionHealthStatus.DEGRADED),
    ]
    assert health.status is RetentionHealthStatus.DEGRADED


async def test_a_frequent_task_without_a_probe_reads_unknown(
    test_tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The public health read never raises for a misregistered task.

    Mutants: it raises; it reads healthy without anything to ask."""

    class _Unprobed(_DueItems):
        has_due = None  # type: ignore[assignment]

    _health_of(monkeypatch, lambda s, at: _Unprobed(s, "tests.health", now=at))

    health = await _health()

    assert health.status is RetentionHealthStatus.UNKNOWN
    assert [task.status for task in health.tasks] == [RetentionHealthStatus.UNKNOWN]


async def test_a_disabled_frequent_task_is_not_probed(
    test_tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutant: health asks the probe of a task the operator turned off."""

    def unasked() -> None:
        raise AssertionError("Health asked a disabled task's probe.")

    _health_of(
        monkeypatch,
        lambda s, at: _DueItems(s, "tests.health", now=at, probe=unasked),
        enabled=False,
    )

    [task] = (await _health()).tasks

    assert (task.status, task.disabled) == (RetentionHealthStatus.DISABLED, True)


class _Held(_DueItems):
    """Keeps its one due item under a hold, reported as an observation."""

    observation_keys = frozenset({"held"})

    async def _remove(self, batch: RetentionBatch) -> RetentionStepResult:
        return RetentionStepResult(
            rows=1,
            effects=(RetentionTenantEffect(tenant_id=None, counts={"held": 1}),),
            exhausted=True,
        )


class _Stuck(_DueItems):
    """Keeps its one due item for a blocked reason that is not 'not due'."""

    blocked_keys = frozenset({"stuck"})

    async def _remove(self, batch: RetentionBatch) -> RetentionStepResult:
        return RetentionStepResult(rows=1, blocked={"stuck": 1}, exhausted=True)


async def _read_back(
    monkeypatch: pytest.MonkeyPatch, registration: RetentionTaskRegistration
) -> tuple[bool, list[str]]:
    """The readback's retention verdict over one registration, through the
    worker's own run; the object store's part is outside this test."""
    from eneo.main import retention_readback

    def registrations(
        settings: Settings, *, now: datetime | None = None
    ) -> tuple[RetentionTaskRegistration, ...]:
        return (registration,)

    async def storage_confirmed(emit: Callable[[str], None]) -> bool:
        return True

    for module in (retention_readback, retention_worker):
        monkeypatch.setattr(module, "retention_task_registrations", registrations)
    monkeypatch.setattr(retention_readback, "_read_back_storage", storage_confirmed)
    lines: list[str] = []
    complete = await retention_readback.read_back_retention(emit=lines.append)
    return complete, lines


async def test_the_readback_runs_a_frequent_task_with_nothing_due(
    test_tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The readback runs every task through the nightly path, so a frequent
    task with nothing due still reports a finished pass.

    Mutant: the readback asks the probe, gets no report and fails."""
    now = await _database_now()
    await _items("tests.quiet", 1, finished=now)

    complete, lines = await _read_back(
        monkeypatch,
        _frequent("tests.quiet", lambda s: _DueItems(s, "tests.quiet", now=now)),
    )

    assert complete, lines
    assert await _left("tests.quiet") == 1


async def test_a_hold_is_an_observation_that_the_readback_accepts(
    test_tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Held content stays and is counted on the job row; it does not fail the
    readback.

    Mutant: a hold is reported as a blocked reason, audited per chunk and
    failing every readback while it lasts."""
    now = await _database_now()
    await _items("tests.held", 1, finished=now - 2 * _AFTER)

    complete, lines = await _read_back(
        monkeypatch,
        _frequent("tests.held", lambda s: _Held(s, "tests.held", now=now)),
    )

    assert complete, lines
    async with _committed() as session:
        counts = await session.scalar(
            sa.select(RetentionJobRuns.counts)
            .where(RetentionJobRuns.task == "tests.held")
            .order_by(RetentionJobRuns.started_at.desc())
            .limit(1)
        )
    assert counts == {"items.held": 1}


@pytest.mark.parametrize("case", ["blocked", "disabled"])
async def test_the_readback_still_fails_on_blocked_or_turned_off_work(
    test_tenant, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """Mutants: a reason the task does not declare as not due is accepted; a
    turned-off task, which leaves its due work in place, is accepted."""
    now = await _database_now()
    await _items("tests.stuck", 1, finished=now - 2 * _AFTER)

    complete, lines = await _read_back(
        monkeypatch,
        _frequent(
            "tests.stuck",
            lambda s: _Stuck(s, "tests.stuck", now=now),
            enabled=case != "disabled",
        ),
    )

    assert not complete
    assert lines[-1] == (
        "  tests.stuck: blocked items.stuck 1"
        if case == "blocked"
        else "  tests.stuck: skipped (disabled_by_deployment_setting)"
    )
