import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Protocol, TypeVar

LeaseRenewal = Callable[[], Awaitable[None]]
_ResultT = TypeVar("_ResultT")
LeasedOperation = Callable[[], Awaitable[_ResultT]]


class OperationCheckpoint(Protocol):
    async def __call__(self) -> None: ...

    async def run(self, operation: LeasedOperation[_ResultT]) -> _ResultT: ...


def _observe_future_result(request: asyncio.Future[_ResultT]) -> None:
    try:
        request.result()
    except BaseException:
        pass


class OperationLeaseCheckpoint:
    """Keep one durable operation lease valid across bounded remote work."""

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
        now = monotonic()
        if self._lease_deadline - now > self._request_budget_seconds:
            return
        await self.renew_now()

    async def run(self, operation: LeasedOperation[_ResultT]) -> _ResultT:
        """Renew during an in-flight mutation and confirm ownership afterward."""
        await self()
        request: asyncio.Future[_ResultT] = asyncio.ensure_future(operation())
        try:
            result = await self._wait_with_heartbeat(request)
        except BaseException:
            request.add_done_callback(_observe_future_result)
            raise

        await self.renew_now()
        return result

    async def _wait_with_heartbeat(
        self,
        request: asyncio.Future[_ResultT],
    ) -> _ResultT:
        heartbeat_seconds = self._lease_seconds / 2
        while True:
            done, _ = await asyncio.wait((request,), timeout=heartbeat_seconds)
            if done:
                return await request
            await self.renew_now()

    async def renew_now(self) -> None:
        renewal_started_at = monotonic()
        await self._renew()
        # The pre-transaction timestamp is a conservative lower bound for the
        # database lease established by the completed renewal.
        self._lease_deadline = renewal_started_at + self._lease_seconds
