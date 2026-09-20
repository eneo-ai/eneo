from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass

from eneo.database.database import sessionmanager
from eneo.flows.domain.flow_run_recovery_policy import (
    FLOW_EXECUTION_HEARTBEAT_INTERVAL_SECONDS,
    FLOW_EXECUTION_HEARTBEAT_MAX_FAILURES,
    FLOW_EXECUTION_HEARTBEAT_TRANSACTION_TIMEOUT_SECONDS,
)
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunExecutionOwner,
    FlowRunRepository,
)
from eneo.main.config import get_settings

logger = logging.getLogger(__name__)


class FlowExecutionOwnershipLost(asyncio.CancelledError):
    pass


@dataclass(slots=True)
class _Invocation:
    owner: FlowRunExecutionOwner
    task: asyncio.Task[object]
    lost: bool = False
    cancellation_requested: bool = False

    def stop(self) -> None:
        if not self.lost:
            self.lost = True
            if asyncio.current_task() is not self.task:
                self.cancellation_requested = self.task.cancel()


_current_invocation: ContextVar[_Invocation | None] = ContextVar(
    "flow_execution_invocation", default=None
)


def current_execution_ownership_lost() -> bool:
    invocation = _current_invocation.get()
    return invocation is not None and invocation.lost


async def execution_ownership_is_lost() -> bool | None:
    invocation = _current_invocation.get()
    if invocation is None:
        return None
    if invocation.lost:
        return True
    async with asyncio.timeout(FLOW_EXECUTION_HEARTBEAT_TRANSACTION_TIMEOUT_SECONDS):
        async with sessionmanager.session() as session, session.begin():
            owned = await FlowRunRepository(session=session).has_execution_ownership(
                owner=invocation.owner
            )
    if not owned:
        invocation.stop()
    return not owned


class FlowExecutionHeartbeats:
    def __init__(self, *, max_active: int) -> None:
        self._max_active = max_active
        self._active: dict[FlowRunExecutionOwner, _Invocation] = {}
        self._loop: asyncio.Task[None] | None = None
        self._failures = 0

    def start(self) -> None:
        if self._loop is None:
            self._loop = asyncio.create_task(
                self._run(), name="flow-execution-heartbeats"
            )

    async def stop(self) -> None:
        for invocation in tuple(self._active.values()):
            invocation.stop()
        loop, self._loop = self._loop, None
        if loop is not None:
            loop.cancel()
            with suppress(asyncio.CancelledError):
                await loop

    @asynccontextmanager
    async def track(self, owner: FlowRunExecutionOwner) -> AsyncGenerator[None]:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Flow execution requires an asyncio task.")
        if owner in self._active or len(self._active) >= self._max_active:
            raise RuntimeError("Flow execution ownership capacity exceeded.")
        invocation = _Invocation(owner, task)
        self._active[owner] = invocation
        self.start()
        token = _current_invocation.set(invocation)
        try:
            yield
            if invocation.lost:
                raise FlowExecutionOwnershipLost()
        except asyncio.CancelledError:
            if invocation.lost:
                if invocation.cancellation_requested:
                    task.uncancel()
                raise FlowExecutionOwnershipLost() from None
            raise
        finally:
            _current_invocation.reset(token)
            del self._active[owner]

    async def renew(self) -> None:
        invocations = tuple(self._active.values())
        if not invocations:
            self._failures = 0
            return
        try:
            async with asyncio.timeout(
                FLOW_EXECUTION_HEARTBEAT_TRANSACTION_TIMEOUT_SECONDS
            ):
                async with sessionmanager.session() as session, session.begin():
                    renewed = await FlowRunRepository(
                        session=session
                    ).renew_execution_heartbeats(
                        owners=[invocation.owner for invocation in invocations]
                    )
        except Exception:
            self._failures += 1
            logger.exception(
                "Flow execution heartbeat renewal failed",
                extra={"consecutive_failures": self._failures},
            )
            if self._failures >= FLOW_EXECUTION_HEARTBEAT_MAX_FAILURES:
                for invocation in invocations:
                    if self._active.get(invocation.owner) is invocation:
                        invocation.stop()
            return
        self._failures = 0
        for invocation in invocations:
            if (
                invocation.owner not in renewed
                and self._active.get(invocation.owner) is invocation
            ):
                invocation.stop()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(FLOW_EXECUTION_HEARTBEAT_INTERVAL_SECONDS)
            await self.renew()


_worker_heartbeats: FlowExecutionHeartbeats | None = None


def execution_heartbeats() -> FlowExecutionHeartbeats:
    global _worker_heartbeats
    if _worker_heartbeats is None:
        _worker_heartbeats = FlowExecutionHeartbeats(
            max_active=get_settings().task_execution_max_jobs
        )
    return _worker_heartbeats
