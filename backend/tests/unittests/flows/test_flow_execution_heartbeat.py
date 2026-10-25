from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.flows.domain.flow_run_recovery_policy import (
    FLOW_EXECUTION_HEARTBEAT_EXPIRY_SECONDS,
    FLOW_EXECUTION_HEARTBEAT_INTERVAL_SECONDS,
    FLOW_EXECUTION_HEARTBEAT_RENEWAL_DEADLINE_SECONDS,
    FLOW_EXECUTION_HEARTBEAT_TRANSACTION_TIMEOUT_SECONDS,
)
from eneo.flows.flow_run_input_envelope import FlowRunInputEnvelopePatch
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunExecutionOwner,
    FlowRunRepository,
)
from eneo.flows.runtime import execution_heartbeat as heartbeat


class _Clock:
    """Stands in for the monotonic clock the heartbeats time leases on."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch) -> _Clock:
    clock = _Clock()
    monkeypatch.setattr(heartbeat, "time", clock)
    return clock


@pytest.fixture
def repo(monkeypatch):
    repo = AsyncMock()
    # A run a renewal left out reads as lost unless a test holds its row.
    repo.has_execution_ownership.return_value = False

    @asynccontextmanager
    async def session_scope():
        session = AsyncMock(spec=AsyncSession)
        yield session

    monkeypatch.setattr(heartbeat.sessionmanager, "session", session_scope)
    monkeypatch.setattr(heartbeat, "FlowRunRepository", lambda **_: repo)
    return repo


@pytest.fixture
def renewal(repo):
    return repo.renew_execution_heartbeats


def _owners(count: int) -> list[FlowRunExecutionOwner]:
    return [FlowRunExecutionOwner(uuid4(), uuid4(), 1) for _ in range(count)]


async def _running(
    manager: heartbeat.FlowExecutionHeartbeats,
    owner: FlowRunExecutionOwner,
    *,
    leased_at: float | None = None,
) -> asyncio.Task[None]:
    """A job that owns the run until it is stopped."""
    started = asyncio.Event()

    async def run() -> None:
        async with manager.track(owner, leased_at=leased_at):
            started.set()
            await asyncio.Event().wait()

    job = asyncio.create_task(run())
    await started.wait()
    return job


async def _stop(
    manager: heartbeat.FlowExecutionHeartbeats, *jobs: asyncio.Task[None]
) -> None:
    await manager.stop()
    await asyncio.gather(*jobs, return_exceptions=True)


@pytest.mark.asyncio
async def test_long_work_renews_without_changing_ownership_and_unregisters(renewal):
    manager = heartbeat.FlowExecutionHeartbeats(max_active=2)
    owner = FlowRunExecutionOwner(uuid4(), uuid4(), 2)
    renewal.return_value = {owner}
    async with manager.track(owner):
        for _ in range(8):
            await manager.renew()
            assert not heartbeat.current_execution_ownership_lost()
    await manager.renew()
    assert renewal.await_count == 8
    await manager.stop()


@pytest.mark.asyncio
async def test_a_job_keeps_the_run_it_tracked_until_its_task_ends(renewal):
    manager = heartbeat.FlowExecutionHeartbeats(max_active=2)
    owner = FlowRunExecutionOwner(uuid4(), uuid4(), 3)
    seen: list[FlowRunExecutionOwner | None] = []

    async def job() -> None:
        seen.append(manager.claimed_run())
        async with manager.track(owner):
            seen.append(manager.claimed_run())
        # Its cleanup runs after the tracking ended and still names the run.
        seen.append(manager.claimed_run())

    task = asyncio.create_task(job())
    await task
    await asyncio.sleep(0)

    assert seen == [None, owner, owner]
    # Another job never sees it, and the ended job's record is gone.
    assert manager.claimed_run() is None
    assert task not in manager._claimed_runs
    await manager.stop()


@pytest.mark.asyncio
async def test_lost_revision_cancels_work_before_another_provider_request(renewal):
    manager = heartbeat.FlowExecutionHeartbeats(max_active=2)
    owner = FlowRunExecutionOwner(uuid4(), uuid4(), 1)
    renewal.return_value = set()
    started = asyncio.Event()
    cancelled = asyncio.Event()
    provider = AsyncMock()

    async def invoke():
        async with manager.track(owner):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            await provider()

    invocation = asyncio.create_task(invoke())
    await started.wait()
    await manager.renew()
    with pytest.raises(heartbeat.FlowExecutionOwnershipLost):
        await invocation
    assert cancelled.is_set()
    provider.assert_not_awaited()
    await manager.renew()
    assert renewal.await_count == 1
    await manager.stop()


@pytest.mark.asyncio
async def test_failed_renewals_stop_a_run_only_once_its_lease_could_expire(
    renewal, clock
):
    manager = heartbeat.FlowExecutionHeartbeats(max_active=1)
    (owner,) = _owners(1)
    renewal.side_effect = OSError("database unavailable")
    tracked_at = clock.now
    job = await _running(manager, owner)

    for _ in range(4):
        clock.now += FLOW_EXECUTION_HEARTBEAT_INTERVAL_SECONDS
        await manager.renew()
        assert not job.done()
    clock.now = tracked_at + FLOW_EXECUTION_HEARTBEAT_RENEWAL_DEADLINE_SECONDS
    await manager.renew()

    with pytest.raises(heartbeat.FlowExecutionOwnershipLost):
        await job
    await manager.stop()


@pytest.mark.asyncio
async def test_a_held_run_keeps_running_while_the_other_renews(repo, renewal, clock):
    manager = heartbeat.FlowExecutionHeartbeats(max_active=2)
    held, free = _owners(2)
    renewal.return_value = {free}
    repo.has_execution_ownership.side_effect = lambda *, owner: owner == held
    tracked_at = clock.now
    jobs = [await _running(manager, owner) for owner in (held, free)]

    for _ in range(4):
        clock.now += FLOW_EXECUTION_HEARTBEAT_INTERVAL_SECONDS
        await manager.renew()
        assert not any(job.done() for job in jobs)
        assert manager._active[free].renewed_at == clock.now
    assert manager._active[held].renewed_at == tracked_at
    await _stop(manager, *jobs)


@pytest.mark.asyncio
async def test_a_held_run_stops_once_its_lease_could_expire_before_the_next_renewal(
    repo, renewal, clock
):
    manager = heartbeat.FlowExecutionHeartbeats(max_active=2)
    held, free = _owners(2)
    renewal.return_value = {free}
    repo.has_execution_ownership.side_effect = lambda *, owner: owner == held
    held_job, free_job = [await _running(manager, owner) for owner in (held, free)]

    clock.now += FLOW_EXECUTION_HEARTBEAT_RENEWAL_DEADLINE_SECONDS - 1
    await manager.renew()
    assert not held_job.done()
    clock.now += 1
    await manager.renew()

    with pytest.raises(heartbeat.FlowExecutionOwnershipLost):
        await held_job
    assert not free_job.done()
    await _stop(manager, free_job)


@pytest.mark.asyncio
async def test_a_confirmed_loss_still_stops_at_once(renewal, clock):
    manager = heartbeat.FlowExecutionHeartbeats(max_active=2)
    lost, free = _owners(2)
    renewal.return_value = {free}
    lost_job, free_job = [await _running(manager, owner) for owner in (lost, free)]

    await manager.renew()

    with pytest.raises(heartbeat.FlowExecutionOwnershipLost):
        await lost_job
    assert not free_job.done()
    await _stop(manager, free_job)


@pytest.mark.asyncio
async def test_a_renewal_restarts_the_owner_deadline(repo, renewal, clock):
    manager = heartbeat.FlowExecutionHeartbeats(max_active=1)
    (owner,) = _owners(1)
    renewal.return_value = {owner}
    job = await _running(manager, owner)
    clock.now += 100
    await manager.renew()

    # Held from here on: the limit counts from the renewal, not the claim.
    renewal.return_value = set()
    repo.has_execution_ownership.return_value = True
    clock.now += 100
    await manager.renew()
    assert not job.done()
    clock.now += FLOW_EXECUTION_HEARTBEAT_RENEWAL_DEADLINE_SECONDS - 100
    await manager.renew()

    with pytest.raises(heartbeat.FlowExecutionOwnershipLost):
        await job
    await manager.stop()


class _FailingCommit:
    @asynccontextmanager
    async def begin(self):
        yield self
        raise OSError("connection lost during commit")


@pytest.mark.asyncio
async def test_a_renewal_whose_commit_failed_does_not_count(
    renewal, clock, monkeypatch
):
    @asynccontextmanager
    async def session_scope():
        yield _FailingCommit()

    monkeypatch.setattr(heartbeat.sessionmanager, "session", session_scope)
    manager = heartbeat.FlowExecutionHeartbeats(max_active=1)
    (owner,) = _owners(1)
    renewal.return_value = {owner}
    tracked_at = clock.now
    job = await _running(manager, owner)

    clock.now += FLOW_EXECUTION_HEARTBEAT_INTERVAL_SECONDS
    await manager.renew()
    renewal.assert_awaited_once()
    assert manager._active[owner].renewed_at == tracked_at
    clock.now = tracked_at + FLOW_EXECUTION_HEARTBEAT_RENEWAL_DEADLINE_SECONDS
    await manager.renew()

    with pytest.raises(heartbeat.FlowExecutionOwnershipLost):
        await job
    await manager.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("commit_seconds", "cycle_seconds"),
    [
        (45, FLOW_EXECUTION_HEARTBEAT_INTERVAL_SECONDS),
        # The loop's worst case: each renewal takes its whole transaction timeout.
        (
            45,
            FLOW_EXECUTION_HEARTBEAT_INTERVAL_SECONDS
            + FLOW_EXECUTION_HEARTBEAT_TRANSACTION_TIMEOUT_SECONDS,
        ),
        (
            FLOW_EXECUTION_HEARTBEAT_RENEWAL_DEADLINE_SECONDS - 1,
            FLOW_EXECUTION_HEARTBEAT_INTERVAL_SECONDS
            + FLOW_EXECUTION_HEARTBEAT_TRANSACTION_TIMEOUT_SECONDS,
        ),
    ],
)
async def test_a_claim_slow_to_commit_counts_against_the_lease_it_stamped(
    repo, renewal, clock, commit_seconds, cycle_seconds
):
    # The claim stamps the first heartbeat; the task tracks the run only once
    # the claim committed, and the renewals follow from then on. A run whose
    # row stays held is stopped before the lease the claim stamped expires.
    manager = heartbeat.FlowExecutionHeartbeats(max_active=1)
    (owner,) = _owners(1)
    renewal.return_value = set()
    repo.has_execution_ownership.return_value = True
    claimed_at = clock.now
    clock.now += commit_seconds
    job = await _running(manager, owner, leased_at=claimed_at)
    invocation = manager._active[owner]

    while not invocation.lost:
        clock.now += cycle_seconds
        assert clock.now - claimed_at < FLOW_EXECUTION_HEARTBEAT_EXPIRY_SECONDS
        await manager.renew()

    assert clock.now - claimed_at >= FLOW_EXECUTION_HEARTBEAT_RENEWAL_DEADLINE_SECONDS
    with pytest.raises(heartbeat.FlowExecutionOwnershipLost):
        await job
    await manager.stop()


@pytest.mark.asyncio
async def test_a_claim_that_committed_too_late_to_be_renewed_does_not_start(
    renewal, clock
):
    manager = heartbeat.FlowExecutionHeartbeats(max_active=1)
    (owner,) = _owners(1)
    claimed_at = clock.now
    clock.now += FLOW_EXECUTION_HEARTBEAT_RENEWAL_DEADLINE_SECONDS
    started = False

    with pytest.raises(heartbeat.FlowExecutionOwnershipLost):
        async with manager.track(owner, leased_at=claimed_at):
            started = True

    assert not started
    assert owner not in manager._active
    assert manager.claimed_run() is None
    await manager.renew()
    renewal.assert_not_awaited()
    await manager.stop()


class _ClaimStopped(Exception):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("commit_seconds", "starts"),
    [(45, True), (FLOW_EXECUTION_HEARTBEAT_RENEWAL_DEADLINE_SECONDS, False)],
)
async def test_a_task_times_its_run_lease_from_before_the_claim(
    clock, monkeypatch, commit_seconds, starts
):
    from types import SimpleNamespace

    from eneo.authentication.principal_types import PrincipalType
    from eneo.flows.runtime import tasks

    manager = heartbeat.FlowExecutionHeartbeats(max_active=1)
    monkeypatch.setattr(manager, "start", lambda: None)
    monkeypatch.setattr(tasks, "execution_heartbeats", lambda: manager)
    monkeypatch.setattr(tasks, "time", clock)
    owner = FlowRunExecutionOwner(uuid4(), uuid4(), 4)
    claimed_at: list[float] = []
    leased_at: list[float] = []

    async def claim(**_):
        claimed_at.append(clock.now)
        clock.now += 1  # the statement that stamps the lease
        return True

    async def slow_commit():
        clock.now += commit_seconds

    session = SimpleNamespace(
        commit=slow_commit, sync_session=SimpleNamespace(autobegin=False)
    )

    @asynccontextmanager
    async def session_scope():
        yield session

    run_repo = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(trace_id=uuid4())),
        mark_running_if_claimable=claim,
    )
    tenant_repo = SimpleNamespace(get=AsyncMock(return_value=object()))
    monkeypatch.setattr(tasks.sessionmanager, "session", session_scope)
    monkeypatch.setattr(
        tasks,
        "Container",
        lambda **_: SimpleNamespace(
            tenant_repo=lambda: tenant_repo, flow_run_repo=lambda: run_repo
        ),
    )
    monkeypatch.setattr(tasks, "UsersRepository", lambda **_: None)

    async def resolve_actor(**_):
        leased_at.append(manager._active[owner].renewed_at)
        raise _ClaimStopped()

    monkeypatch.setattr(tasks, "_resolve_flow_run_actor", resolve_actor)

    with pytest.raises(
        _ClaimStopped if starts else heartbeat.FlowExecutionOwnershipLost
    ):
        await tasks._execute_flow_run_async(
            run_id=owner.run_id,
            flow_id=uuid4(),
            tenant_id=owner.tenant_id,
            run_revision=owner.revision,
            principal_type=PrincipalType.USER,
            principal_user_id=uuid4(),
            principal_service_id=None,
            task_id="job-1",
            retry_count=0,
            invocation_deadline=None,
        )

    # Read before the claim stamped the lease, not once its commit returned.
    assert leased_at == (claimed_at if starts else [])
    await manager.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("commit_seconds", "starts"),
    [(45, True), (FLOW_EXECUTION_HEARTBEAT_RENEWAL_DEADLINE_SECONDS, False)],
)
async def test_the_executor_times_its_run_lease_from_before_the_claim(
    clock, monkeypatch, commit_seconds, starts
):
    """The executor's own claim times the lease as the task's does."""
    from types import SimpleNamespace

    from eneo.flows.runtime import executor as flow_executor

    manager = heartbeat.FlowExecutionHeartbeats(max_active=1)
    monkeypatch.setattr(manager, "start", lambda: None)
    monkeypatch.setattr(flow_executor, "execution_heartbeats", lambda: manager)
    monkeypatch.setattr(flow_executor, "time", clock)
    owner = FlowRunExecutionOwner(uuid4(), uuid4(), 4)
    claimed_at: list[float] = []
    leased_at: list[float] = []

    async def claim(**_):
        claimed_at.append(clock.now)
        clock.now += 1  # the statement that stamps the lease
        return True

    async def slow_commit():
        clock.now += commit_seconds

    async def execute_claimed(**_):
        leased_at.append(manager._active[owner].renewed_at)
        return {"status": "completed"}

    lost = {"status": "lost"}
    executor = flow_executor.FlowRunExecutor.__new__(flow_executor.FlowRunExecutor)
    executor.flow_run_repo = SimpleNamespace(mark_running_if_claimable=claim)
    executor._commit = slow_commit
    executor._rollback = AsyncMock()
    executor.execute_claimed = execute_claimed
    executor._return_after_losing_the_run = AsyncMock(return_value=lost)

    result = await executor.execute(
        run_id=owner.run_id,
        flow_id=uuid4(),
        tenant_id=owner.tenant_id,
        run_revision=owner.revision,
        dispatch_task_id="job-1",
        retry_count=0,
    )

    # Read before the claim stamped the lease, not once its commit returned.
    assert leased_at == (claimed_at if starts else [])
    assert result == ({"status": "completed"} if starts else lost)
    await manager.stop()


@pytest.mark.asyncio
async def test_a_renewal_slow_to_clean_up_holds_up_neither_the_cycle_nor_the_limit(
    repo, renewal, clock, monkeypatch
):
    # asyncio.timeout bounds the renewal's statements, not the rollback and
    # close that follow its cancellation.
    monkeypatch.setattr(
        heartbeat, "FLOW_EXECUTION_HEARTBEAT_TRANSACTION_TIMEOUT_SECONDS", 0.05
    )
    closed = asyncio.Event()

    @asynccontextmanager
    async def slow_close():
        try:
            yield AsyncMock(spec=AsyncSession)
        finally:
            await closed.wait()

    async def hang(**_):
        await asyncio.Event().wait()

    monkeypatch.setattr(heartbeat.sessionmanager, "session", slow_close)
    renewal.side_effect = hang
    manager = heartbeat.FlowExecutionHeartbeats(max_active=2)
    stale, healthy = _owners(2)
    stale_since = clock.now
    stale_job = await _running(manager, stale)
    clock.now += 100
    healthy_job = await _running(manager, healthy)

    clock.now += FLOW_EXECUTION_HEARTBEAT_INTERVAL_SECONDS
    async with asyncio.timeout(1):
        await manager.renew()
    # Still closing: the next cycle starts no second renewal, yet stops the
    # run that has reached its limit on time.
    clock.now = stale_since + FLOW_EXECUTION_HEARTBEAT_RENEWAL_DEADLINE_SECONDS
    async with asyncio.timeout(1):
        await manager.renew()
    renewal.assert_awaited_once()
    with pytest.raises(heartbeat.FlowExecutionOwnershipLost):
        await stale_job
    assert not healthy_job.done()

    # Once the close is over, the next cycle renews the healthy run again.
    closed.set()
    renewal.side_effect = None
    renewal.return_value = {healthy}
    for _ in range(10):
        await asyncio.sleep(0)
    clock.now += FLOW_EXECUTION_HEARTBEAT_INTERVAL_SECONDS
    await manager.renew()
    assert renewal.await_args.kwargs == {"owners": [healthy]}
    assert manager._active[healthy].renewed_at == clock.now
    await _stop(manager, healthy_job)


@pytest.mark.asyncio
async def test_a_stopped_run_still_cleaning_up_is_not_renewed_nor_delays_the_others(
    renewal, clock
):
    manager = heartbeat.FlowExecutionHeartbeats(max_active=2)
    lost, healthy = _owners(2)
    renewal.return_value = {healthy}
    started = asyncio.Event()
    cleaned_up = asyncio.Event()

    async def slow_to_unwind() -> None:
        async with manager.track(lost):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await cleaned_up.wait()

    lost_job = asyncio.create_task(slow_to_unwind())
    await started.wait()
    healthy_job = await _running(manager, healthy)
    await manager.renew()
    assert manager._active[lost].lost

    clock.now += FLOW_EXECUTION_HEARTBEAT_INTERVAL_SECONDS
    async with asyncio.timeout(1):
        await manager.renew()
    assert renewal.await_args.kwargs == {"owners": [healthy]}
    assert manager._active[healthy].renewed_at == clock.now

    cleaned_up.set()
    with pytest.raises(heartbeat.FlowExecutionOwnershipLost):
        await lost_job
    await _stop(manager, healthy_job)


@pytest.mark.asyncio
async def test_one_loop_renews_two_invocations_and_stops_after_their_exit(
    renewal, monkeypatch
):
    monkeypatch.setattr(heartbeat, "FLOW_EXECUTION_HEARTBEAT_INTERVAL_SECONDS", 0.01)
    manager = heartbeat.FlowExecutionHeartbeats(max_active=2)
    owners = [FlowRunExecutionOwner(uuid4(), uuid4(), 1) for _ in range(2)]
    renewed = asyncio.Event()
    release = asyncio.Event()
    ready = asyncio.Barrier(3)
    batches = []

    async def renew(*, owners):
        batches.append(tuple(owners))
        if len(batches) == 3:
            renewed.set()
        return set(owners)

    renewal.side_effect = renew

    async def invoke(owner):
        async with manager.track(owner):
            await ready.wait()
            await release.wait()

    async with asyncio.TaskGroup() as group:
        for owner in owners:
            group.create_task(invoke(owner))
        await ready.wait()
        await asyncio.wait_for(renewed.wait(), timeout=2)
        release.set()
    assert len(batches) >= 3
    assert all(set(batch) == set(owners) for batch in batches)
    before = renewal.await_count
    await manager.renew()
    assert renewal.await_count == before
    await manager.stop()


@pytest.mark.asyncio
async def test_scope_unregisters_on_exception_and_external_cancellation(renewal):
    manager = heartbeat.FlowExecutionHeartbeats(max_active=1)
    owner = FlowRunExecutionOwner(uuid4(), uuid4(), 1)
    for error in (ValueError("execution failed"), asyncio.CancelledError()):
        with pytest.raises(type(error)):
            async with manager.track(owner):
                raise error
        await manager.renew()
    renewal.assert_not_awaited()
    await manager.stop()


@pytest.mark.asyncio
async def test_database_ownership_loss_prevents_next_request_without_leaking_cancellation(
    monkeypatch,
):
    manager = heartbeat.FlowExecutionHeartbeats(max_active=1)
    owner = FlowRunExecutionOwner(uuid4(), uuid4(), 1)
    repo = AsyncMock()
    repo.has_execution_ownership.return_value = False

    @asynccontextmanager
    async def session_scope():
        yield AsyncMock(spec=AsyncSession)

    monkeypatch.setattr(heartbeat.sessionmanager, "session", session_scope)
    monkeypatch.setattr(heartbeat, "FlowRunRepository", lambda **_: repo)
    provider = AsyncMock()
    task = asyncio.current_task()
    cancellations_before = task.cancelling()
    with pytest.raises(heartbeat.FlowExecutionOwnershipLost):
        async with manager.track(owner):
            if await heartbeat.execution_ownership_is_lost():
                raise heartbeat.FlowExecutionOwnershipLost()
            await provider()
    repo.has_execution_ownership.assert_awaited_once_with(owner=owner)
    provider.assert_not_awaited()
    assert task.cancelling() == cancellations_before
    await manager.stop()


def test_worker_stalled_error_retains_typed_recovery_facts():
    from eneo.flows.flow_run_error import dump_flow_run_error, parse_flow_run_error

    payload = {
        "code": "flow_worker_stalled",
        "message": "Execution heartbeat expired.",
        "details": {
            "recovery": {
                "reason": "execution_heartbeat_expired",
                "heartbeat_at": "2026-09-20T18:00:00Z",
                "expires_at": "2026-09-20T18:03:00Z",
            },
        },
    }
    error = parse_flow_run_error(payload)
    assert error.code == "flow_worker_stalled"
    assert dump_flow_run_error(error)["details"] == payload["details"]


@pytest.mark.asyncio
async def test_paused_execution_cannot_publish_transcript_after_recovery():
    from eneo.flows.domain.step_output import inline_transcript

    manager = heartbeat.FlowExecutionHeartbeats(max_active=1)
    owner = FlowRunExecutionOwner(uuid4(), uuid4(), 1)
    session = AsyncMock(spec=AsyncSession)
    session.scalar.side_effect = [owner.run_id, None]
    repo = FlowRunRepository(session=session)
    try:
        with pytest.raises(heartbeat.FlowExecutionOwnershipLost):
            async with manager.track(owner):
                await repo.update_input_payload(
                    run_id=owner.run_id,
                    tenant_id=owner.tenant_id,
                    input_payload_patch=FlowRunInputEnvelopePatch.transcription(
                        transcript=inline_transcript(
                            text="Late provider result",
                            source_step_id=uuid4(),
                            source_attempt_no=1,
                        )
                    ),
                )
                await session.commit()
        from sqlalchemy.dialects import postgresql

        lock, eligibility = [call.args[0] for call in session.scalar.await_args_list]
        assert "FOR UPDATE" in str(lock)
        sql = str(eligibility.compile(dialect=postgresql.dialect()))
        assert "flow_runs.revision =" in sql
        assert "flow_runs.status =" in sql
        assert "flow_runs.execution_heartbeat_at > clock_timestamp()" in sql
        session.rollback.assert_awaited_once()
        session.execute.assert_not_awaited()
        session.commit.assert_not_awaited()
    finally:
        await manager.stop()


def test_the_worker_heartbeats_check_the_run_capacity_against_the_executor_slots_once(
    monkeypatch,
):
    from types import SimpleNamespace

    checked: list[int] = []
    monkeypatch.setattr(heartbeat, "_worker_heartbeats", None)
    monkeypatch.setattr(
        heartbeat,
        "get_settings",
        lambda: SimpleNamespace(task_execution_max_jobs=3),
    )
    monkeypatch.setattr(
        heartbeat,
        "warn_when_run_capacity_exceeds_executor_slots",
        lambda *, executor_slots: checked.append(executor_slots),
    )

    first = heartbeat.execution_heartbeats()
    second = heartbeat.execution_heartbeats()

    assert first is second
    assert checked == [3]
