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
