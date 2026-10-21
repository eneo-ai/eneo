"""Flow run worker: durable execution on the sessionless long-running path.

Job status uses explicit compare-and-swap repo calls; the executor owns the
per-step transaction boundaries through ``Container.session_scope()``;
provider calls run with no transaction open. A heartbeat refreshes
``flow_runs.heartbeat_at`` so the stale-run reconciler can tell a live
worker from a crashed one.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.flows.flow_models import FlowRunStatus
from eneo.flows.flow_run_executor import OUTCOME_UNKNOWN
from eneo.flows.lifecycle import finish_run
from eneo.jobs.task_models import FlowRunParams
from eneo.main.container.container import Container
from eneo.main.container.container_overrides import override_user
from eneo.main.logging import get_logger
from eneo.main.models import ChannelType, Status
from eneo.worker.task_manager import TaskManager
from eneo.worker.worker import Worker

logger = get_logger(__name__)

worker = Worker()

HEARTBEAT_INTERVAL_SECONDS = 30
# Heartbeat every 30 s; 10 minutes of silence means the worker is gone.
FLOW_RUN_STALE_AFTER = timedelta(minutes=10)
RECONCILE_BATCH_SIZE = 20
RUN_INTERRUPTED = "flow_run_interrupted_outcome_unknown"


@contextlib.asynccontextmanager
async def _run_heartbeat(container: Container, run_id: UUID):
    """Refresh the run heartbeat while executing; cancel the owner when the
    lease is lost (run no longer running, e.g. cancelled or reconciled)."""
    owner = asyncio.current_task()
    stop = asyncio.Event()

    async def beat() -> None:
        while not stop.is_set():
            try:
                async with asyncio.timeout(HEARTBEAT_INTERVAL_SECONDS):
                    await stop.wait()
                return
            except TimeoutError:
                pass
            async with Container.session_scope():
                alive = await container.flow_repo().touch_heartbeat(run_id)
            if not alive and owner is not None:
                logger.warning(
                    "Flow run lease lost; stopping executor",
                    extra={"run_id": str(run_id)},
                )
                owner.cancel()
                return

    beat_task = asyncio.create_task(beat())
    try:
        yield
    finally:
        stop.set()
        with contextlib.suppress(asyncio.CancelledError):
            await beat_task


@worker.long_running_function()
async def run_flow(job_id: UUID, params: FlowRunParams, container: Container):
    async with Container.session_scope():
        started = await container.job_repo().mark_job_started(job_id)
    if not started:
        # Duplicate delivery or a job another worker already owns.
        return None

    # The run executes as its persisted principal, which may differ from the
    # dispatching user (a reviewer resuming someone else's run).
    dispatcher = container.user()
    async with Container.session_scope():
        run_row = await container.flow_repo().get_run(params.id, dispatcher.tenant_id)
        principal_id = run_row.principal_user_id if run_row is not None else None
    if principal_id is not None and principal_id != dispatcher.id:
        async with Container.session_scope():
            principal = await container.user_repo().get_user_by_id(id=principal_id)
        if principal is not None:
            override_user(container=container, user=principal)

    user = container.user()
    task_manager = TaskManager(
        user=user,
        job_id=job_id,
        channel_type=ChannelType.FLOW_RUN_UPDATES,
        resource_id=params.id,
    )
    task_manager.additional_data = {"flow_id": str(params.flow_id)}
    await task_manager.publish_status(Status.IN_PROGRESS)

    try:
        async with _run_heartbeat(container, params.id):
            await container.flow_run_executor().execute_run(params.id, user.tenant_id)
        async with Container.session_scope():
            await container.job_repo().mark_job_completed(
                job_id, f"/api/v1/flows/{params.flow_id}/runs/{params.id}/"
            )
        await task_manager.publish_status(Status.COMPLETE)
        return None
    except (Exception, asyncio.CancelledError) as exc:
        async with Container.session_scope():
            await container.job_repo().mark_job_failed_if_running(
                job_id, str(exc)[:512] or "flow run interrupted"
            )
        await task_manager.publish_status(Status.FAILED)
        raise


@worker.cron_job(manages_own_session=True, minute={0, 10, 20, 30, 40, 50})
async def reconcile_stale_flow_runs(container: Container) -> None:
    """Terminalize runs whose worker died mid-flight.

    Only ``running`` runs are eligible: ``awaiting_review`` is parked by
    design and ``queued`` runs are re-driven by durable dispatch. In-flight
    attempts become ``outcome_unknown`` and their provider calls are never
    repeated.
    """
    session = cast(AsyncSession, container.session())
    stale_before = datetime.now(UTC) - FLOW_RUN_STALE_AFTER
    async with session.begin():
        repo = container.flow_repo()
        runs = await repo.get_stale_running_runs(
            stale_before=stale_before, limit=RECONCILE_BATCH_SIZE
        )
        for run in runs:
            await repo.mark_started_attempts_outcome_unknown(run.id)
            await repo.fail_running_step_results(
                run.id,
                error_code=OUTCOME_UNKNOWN,
                error_message="The worker stopped before the step's outcome was "
                "recorded; the call is not repeated.",
            )
            await finish_run(
                repo,
                container.audit_service(),
                run.id,
                run.tenant_id,
                FlowRunStatus.FAILED,
                error={
                    "code": RUN_INTERRUPTED,
                    "message": "The run was interrupted and its last step's "
                    "outcome is unknown.",
                },
                expected_statuses=(FlowRunStatus.RUNNING,),
            )
            if run.job_id is not None:
                await container.job_repo().mark_job_failed_if_running(
                    run.job_id, "flow run reconciled after worker loss"
                )
            logger.info("Reconciled stale flow run", extra={"run_id": str(run.id)})


@worker.cron_job(manages_own_session=True, second=0)
async def maintain_flow_run_lifecycle(container: Container) -> None:
    """Retire unfinished runs of deleted flows and expire parked reviews."""
    session = cast(AsyncSession, container.session())
    async with session.begin():
        repo = container.flow_repo()
        for run_id, tenant_id, code in await repo.runs_needing_maintenance():
            await finish_run(
                repo,
                container.audit_service(),
                run_id,
                tenant_id,
                FlowRunStatus.CANCELLED
                if code == "flow_deleted"
                else FlowRunStatus.FAILED,
                error={
                    "code": code,
                    "message": "The flow was deleted."
                    if code == "flow_deleted"
                    else "The review deadline passed.",
                },
                expired=code == "flow_review_expired",
            )
