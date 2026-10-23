from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass

from eneo.database.database import sessionmanager
from eneo.flows.domain.flow_run_exceptions import (
    FlowExecutionOwnershipLost as FlowExecutionOwnershipLost,
)
from eneo.flows.domain.flow_run_recovery_policy import (
    FLOW_EXECUTION_HEARTBEAT_INTERVAL_SECONDS,
    FLOW_EXECUTION_HEARTBEAT_MAX_FAILURES,
    FLOW_EXECUTION_HEARTBEAT_TRANSACTION_TIMEOUT_SECONDS,
    FLOW_WORKER_SHUTDOWN_WRITE_TIMEOUT_SECONDS,
)
from eneo.flows.flow_runtime_policy import warn_when_run_capacity_exceeds_executor_slots
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunExecutionOwner,
    FlowRunRepository,
    flow_run_execution_owner,
)
from eneo.main.config import get_settings

logger = logging.getLogger(__name__)


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
        self._worker: asyncio.Task[object] | None = None
        # Every flow run job task, from its first statement until the task
        # itself has ended: a job a shutdown cancels may still be claiming its
        # run or cleaning up, and only then starts its shutdown write.
        self._jobs: set[asyncio.Task[object]] = set()
        self._shutdown_writes: set[asyncio.Task[None]] = set()
        # Set once stop() has waited for the jobs: the worker then closes its
        # database, so a write would meet it closed.
        self._closed = False

    def start(self) -> None:
        if self._loop is None:
            self._loop = asyncio.create_task(
                self._run(), name="flow-execution-heartbeats"
            )

    def attach_to_worker(self) -> None:
        """Start renewing for the ARQ worker whose startup hook calls this,
        and keep that hook's task: ARQ's poll task, which ARQ cancels only
        when the worker shuts down (on SIGTERM/SIGINT once job_completion_wait
        is over, or on close), right after cancelling its jobs. A job timeout,
        an abort or a lost ownership cancels a job and leaves the poll task."""
        self._worker = asyncio.current_task()
        self._closed = False
        self.start()

    def worker_is_shutting_down(self) -> bool:
        worker = self._worker
        return worker is not None and (worker.done() or worker.cancelling() > 0)

    def hold_job(self) -> None:
        """Keep the calling flow run job until its task has ended, so ``stop``
        waits for a shutdown write the job starts at any point of its run."""
        task = asyncio.current_task()
        if task is not None and task not in self._jobs:
            self._jobs.add(task)
            task.add_done_callback(self._jobs.discard)

    def run_shutdown_write(
        self, write: Coroutine[object, object, None]
    ) -> asyncio.Task[None] | None:
        """Run a terminal write a worker shutdown started, as a task ``stop``
        waits for: a second cancellation ends the job that started it, not
        the write. None once ``stop`` closed: the worker is closing its
        database, so the heartbeat reaper ends the run instead. The write
        bounds its own time."""
        if self._closed:
            write.close()
            logger.warning(
                "Flow run left to the heartbeat reaper: its job ended after the "
                "worker shutdown stopped waiting for it"
            )
            return None
        task = asyncio.create_task(write, name="flow-run-shutdown-write")
        self._shutdown_writes.add(task)
        task.add_done_callback(self._shutdown_writes.discard)
        return task

    async def stop(self) -> None:
        """Stop renewing after the flow run jobs have ended and the shutdown
        writes they started are done, so the worker closes its database only
        then. The wait for the jobs is bounded; a job still running past it
        starts no write (``run_shutdown_write``). Each write bounds its own
        time."""
        jobs = self._jobs - {asyncio.current_task()}
        if jobs:
            _, unfinished = await asyncio.wait(
                jobs, timeout=FLOW_WORKER_SHUTDOWN_WRITE_TIMEOUT_SECONDS
            )
            if unfinished:
                logger.warning(
                    "Flow run jobs still running when the worker shutdown "
                    "stopped waiting; the heartbeat reaper ends their runs",
                    extra={"jobs": len(unfinished)},
                )
        self._closed = True
        if self._shutdown_writes:
            await asyncio.gather(*self._shutdown_writes, return_exceptions=True)
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
        owner_token = flow_run_execution_owner.set(owner)
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
            flow_run_execution_owner.reset(owner_token)
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
        slots = get_settings().task_execution_max_jobs
        # First built when the execution worker starts: the one place that holds
        # the executor slots, so the configured run capacity is checked once.
        warn_when_run_capacity_exceeds_executor_slots(executor_slots=slots)
        _worker_heartbeats = FlowExecutionHeartbeats(max_active=slots)
    return _worker_heartbeats
