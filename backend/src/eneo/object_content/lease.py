from collections.abc import Awaitable, Callable
from time import monotonic

LeaseRenewal = Callable[[], Awaitable[None]]


class OperationLeaseCheckpoint:
    """Amortize durable lease renewal while preserving one SDK-call budget."""

    def __init__(
        self,
        *,
        lease_started_at: float,
        lease_seconds: float,
        request_budget_seconds: float,
        renew: LeaseRenewal,
    ) -> None:
        self._lease_deadline = lease_started_at + lease_seconds
        self._lease_seconds = lease_seconds
        self._request_budget_seconds = request_budget_seconds
        self._renew = renew

    async def __call__(self) -> None:
        renewal_started_at = monotonic()
        if self._lease_deadline - renewal_started_at > self._request_budget_seconds:
            return
        await self._renew()
        # The pre-transaction timestamp is a conservative lower bound for the
        # database lease established by the completed renewal.
        self._lease_deadline = renewal_started_at + self._lease_seconds
