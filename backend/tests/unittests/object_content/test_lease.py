import asyncio

import pytest

from eneo.object_content import lease as lease_module
from eneo.object_content.lease import OperationLeaseCheckpoint


@pytest.mark.asyncio
async def test_checkpoint_amortizes_renewal_from_a_conservative_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    renewals: list[float] = []
    monkeypatch.setattr(lease_module, "monotonic", lambda: clock[0])

    async def renew() -> None:
        renewals.append(clock[0])
        clock[0] += 10  # Simulate a slow database transaction.

    checkpoint = OperationLeaseCheckpoint(
        lease_started_at=0,
        lease_seconds=300,
        request_budget_seconds=200,
        renew=renew,
    )

    clock[0] = 99
    await checkpoint()
    assert renewals == []

    clock[0] = 100
    await checkpoint()
    assert renewals == [100]

    # The new local deadline is anchored before the slow renewal, so it never
    # overestimates the durable lease established inside that transaction.
    clock[0] = 200
    await checkpoint()
    assert renewals == [100, 200]


@pytest.mark.asyncio
async def test_checkpoint_renews_during_and_after_an_in_flight_operation() -> None:
    renewals = 0
    renewed = asyncio.Event()
    started = asyncio.Event()
    release = asyncio.Event()

    async def renew() -> None:
        nonlocal renewals
        renewals += 1
        renewed.set()

    async def operation() -> str:
        started.set()
        await release.wait()
        return "stored"

    checkpoint = OperationLeaseCheckpoint(
        lease_started_at=lease_module.monotonic(),
        lease_seconds=0.04,
        request_budget_seconds=0.01,
        renew=renew,
    )
    running = asyncio.create_task(checkpoint.run(operation))
    await started.wait()
    await asyncio.wait_for(renewed.wait(), timeout=1)

    assert renewals >= 1
    release.set()
    assert await running == "stored"
    assert renewals >= 2


@pytest.mark.asyncio
async def test_checkpoint_rejects_a_result_when_final_renewal_fails() -> None:
    operation_completed = False

    async def renew() -> None:
        raise RuntimeError("lease changed")

    async def operation() -> str:
        nonlocal operation_completed
        operation_completed = True
        return "stored"

    checkpoint = OperationLeaseCheckpoint(
        lease_started_at=lease_module.monotonic(),
        lease_seconds=300,
        request_budget_seconds=1,
        renew=renew,
    )

    with pytest.raises(RuntimeError, match="lease changed"):
        await checkpoint.run(operation)
    assert operation_completed


@pytest.mark.asyncio
async def test_checkpoint_observes_late_failure_after_renewal_loss() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()

    async def renew() -> None:
        raise RuntimeError("lease changed")

    async def operation() -> str:
        started.set()
        await release.wait()
        completed.set()
        raise RuntimeError("late SDK failure")

    checkpoint = OperationLeaseCheckpoint(
        lease_started_at=lease_module.monotonic(),
        lease_seconds=0.04,
        request_budget_seconds=0.01,
        renew=renew,
    )
    running = asyncio.create_task(checkpoint.run(operation))
    await started.wait()

    with pytest.raises(RuntimeError, match="lease changed"):
        await running

    release.set()
    await asyncio.wait_for(completed.wait(), timeout=1)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_checkpoint_observes_an_in_flight_operation_after_cancellation() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()

    async def operation() -> str:
        started.set()
        await release.wait()
        completed.set()
        return "stored"

    checkpoint = OperationLeaseCheckpoint(
        lease_started_at=lease_module.monotonic(),
        lease_seconds=300,
        request_budget_seconds=1,
        renew=lambda: asyncio.sleep(0),
    )
    running = asyncio.create_task(checkpoint.run(operation))
    await started.wait()
    running.cancel()

    with pytest.raises(asyncio.CancelledError):
        await running

    release.set()
    await asyncio.wait_for(completed.wait(), timeout=1)
    await asyncio.sleep(0)
