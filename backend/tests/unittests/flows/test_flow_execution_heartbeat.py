from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.flows.flow_run_input_envelope import FlowRunInputEnvelopePatch
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunExecutionOwner,
    FlowRunRepository,
)
from eneo.flows.runtime import execution_heartbeat as heartbeat


@pytest.fixture
def renewal(monkeypatch):
    repo = AsyncMock()

    @asynccontextmanager
    async def session_scope():
        session = AsyncMock(spec=AsyncSession)
        yield session

    monkeypatch.setattr(heartbeat.sessionmanager, "session", session_scope)
    monkeypatch.setattr(heartbeat, "FlowRunRepository", lambda **_: repo)
    return repo.renew_execution_heartbeats


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
async def test_three_consecutive_renewal_failures_stop_execution(renewal):
    manager = heartbeat.FlowExecutionHeartbeats(max_active=1)
    owner = FlowRunExecutionOwner(uuid4(), uuid4(), 1)
    renewal.side_effect = OSError("database unavailable")
    started = asyncio.Event()

    async def invoke():
        async with manager.track(owner):
            started.set()
            await asyncio.Event().wait()

    invocation = asyncio.create_task(invoke())
    await started.wait()
    for _ in range(2):
        await manager.renew()
        assert not invocation.done()
    await manager.renew()
    with pytest.raises(heartbeat.FlowExecutionOwnershipLost):
        await invocation
    await manager.stop()


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
