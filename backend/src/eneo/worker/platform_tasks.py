from __future__ import annotations

from typing import cast
from uuid import UUID

from arq.worker import func as arq_func

from eneo.flows.application.flow_run_audit_outbox_policy import (
    FLOW_AUDIT_OUTBOX_DELIVERY_INTERVAL_SECONDS,
)
from eneo.flows.application.flow_webhook_delivery_policy import (
    FLOW_WEBHOOK_DELIVERY_INTERVAL_SECONDS,
    flow_webhook_delivery_budget,
    flow_webhook_delivery_request,
)
from eneo.flows.domain.flow_run_recovery_policy import (
    FLOW_RUNNING_RECONCILE_INTERVAL_SECONDS,
    flow_task_hard_timeout_seconds,
)
from eneo.flows.flow_run_dispatch_request import FlowRunDispatchTaskKwargs
from eneo.flows.runtime.execution_heartbeat import execution_heartbeats
from eneo.flows.runtime.tasks import (
    deliver_flow_audit_outbox,
    deliver_flow_webhook_outbox,
    drain_retired_flow_runs,
    execute_flow_run_task,
    reconcile_expired_review_checkpoints,
    reconcile_stale_running_runs,
    redispatch_stale_queued_runs,
)
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.tasks.contracts import TaskEnqueueStatus
from eneo.tasks.routing import (
    FLOW_DELIVER_AUDIT_OUTBOX_TASK,
    FLOW_DELIVER_WEBHOOK_OUTBOX_TASK,
    FLOW_DRAIN_RETIRED_RUNS_TASK,
    FLOW_DRAIN_WEBHOOK_OUTBOX_TASK,
    FLOW_EXECUTE_TASK,
    FLOW_RECONCILE_REVIEW_EXPIRY_TASK,
    FLOW_RECONCILE_RUNNING_TASK,
    FLOW_REDISPATCH_STALE_QUEUED_TASK,
)
from eneo.worker.worker import ARQContext, Worker, traced_job

execution_worker = Worker()
maintenance_worker = Worker()


@execution_worker.long_running_function(
    with_user=False,
    keep_result=60,
    name=FLOW_EXECUTE_TASK,
)
async def execute_flow_run(
    task_id: UUID,
    params: object,
    container: Container,
) -> dict[str, str]:
    del container
    payload = cast(FlowRunDispatchTaskKwargs, params)
    return await execute_flow_run_task(
        **payload,
        task_id=str(task_id),
        retry_count=0,
    )


@maintenance_worker.cron_job(
    manages_own_session=True,
    name=FLOW_RECONCILE_RUNNING_TASK,
    second=set(range(0, 60, FLOW_RUNNING_RECONCILE_INTERVAL_SECONDS)),
    keep_result=60,
)
async def reconcile_running(*, container: Container) -> dict[str, int | str]:
    del container
    return await reconcile_stale_running_runs()


@maintenance_worker.cron_job(
    manages_own_session=True,
    name=FLOW_RECONCILE_REVIEW_EXPIRY_TASK,
    second=0,
    keep_result=60,
)
async def reconcile_review_expiry(*, container: Container) -> dict[str, int | str]:
    del container
    return await reconcile_expired_review_checkpoints()


@maintenance_worker.cron_job(
    manages_own_session=True,
    name=FLOW_REDISPATCH_STALE_QUEUED_TASK,
    second={0, 30},
    keep_result=60,
)
async def redispatch_stale_queued(*, container: Container) -> dict[str, int | str]:
    del container
    return await redispatch_stale_queued_runs()


@maintenance_worker.cron_job(
    manages_own_session=True,
    name=FLOW_DRAIN_RETIRED_RUNS_TASK,
    second=set(range(0, 60, get_settings().flow_retired_run_drain_interval_seconds)),
    keep_result=60,
)
async def drain_retired_runs(*, container: Container) -> dict[str, int | str]:
    del container
    return await drain_retired_flow_runs()


@maintenance_worker.cron_job(
    manages_own_session=True,
    name=FLOW_DELIVER_AUDIT_OUTBOX_TASK,
    second=set(range(0, 60, FLOW_AUDIT_OUTBOX_DELIVERY_INTERVAL_SECONDS)),
    keep_result=60,
)
async def deliver_audit_outbox(*, container: Container) -> dict[str, int | str]:
    del container
    return await deliver_flow_audit_outbox()


@maintenance_worker.cron_job(
    manages_own_session=True,
    name=FLOW_DELIVER_WEBHOOK_OUTBOX_TASK,
    second=set(range(0, 60, FLOW_WEBHOOK_DELIVERY_INTERVAL_SECONDS)),
    keep_result=60,
)
async def deliver_webhook_outbox(*, container: Container) -> dict[str, int | str]:
    """Request the webhook outbox job: recovery for deliveries their run's own
    request did not reach. Each tick has its own ARQ job id, so a tick that
    ended never holds back the next one."""
    result = await container.platform_task_enqueuer().enqueue(
        flow_webhook_delivery_request()
    )
    if result.status is not TaskEnqueueStatus.ACCEPTED:
        raise RuntimeError(
            f"{FLOW_DELIVER_WEBHOOK_OUTBOX_TASK} could not request delivery: "
            f"{result.status.value}"
        )
    return {"status": result.status.value}


async def drain_webhook_outbox(
    ctx: ARQContext, payload: object
) -> dict[str, int | str]:
    """The webhook outbox job. ``payload`` is its request's empty payload."""
    del ctx, payload
    return await deliver_flow_webhook_outbox()


async def execution_startup(ctx: ARQContext) -> None:
    await execution_worker.on_startup(ctx)
    execution_heartbeats().attach_to_worker()


async def execution_shutdown(ctx: ARQContext) -> None:
    try:
        await execution_heartbeats().stop()
    finally:
        await execution_worker.on_shutdown(ctx)


class PlatformExecutionWorkerSettings:
    settings = get_settings()
    functions = execution_worker.functions
    cron_jobs: list[object] = []
    redis_settings = execution_worker.redis_settings
    on_startup = execution_startup
    on_shutdown = execution_shutdown
    retry_jobs = execution_worker.retry_jobs
    job_serializer = execution_worker.job_serializer
    job_deserializer = execution_worker.job_deserializer
    # The task must persist its timeout before ARQ cancels its error handler.
    job_timeout = flow_task_hard_timeout_seconds(
        task_timeout_seconds=settings.task_execution_timeout_seconds
    )
    max_jobs = settings.task_execution_max_jobs
    queue_name = settings.task_execution_queue
    expires_extra_ms = execution_worker.expires_extra_ms
    health_check_interval = execution_worker.health_check_interval
    allow_abort_jobs = execution_worker.allow_abort_jobs
    job_completion_wait = execution_worker.job_completion_wait
    after_job_end = execution_worker.after_job_end


class PlatformMaintenanceWorkerSettings:
    settings = get_settings()
    functions = [
        arq_func(
            traced_job("job", drain_webhook_outbox),
            name=FLOW_DRAIN_WEBHOOK_OUTBOX_TASK,
            # An ended job keeps nothing under its fixed key, so the next
            # request starts a new job.
            keep_result=0,
            # The job stops itself at its hard stop; ARQ only cancels a job
            # that overruns.
            timeout=flow_webhook_delivery_budget().job_timeout_seconds,
            # One try: a job killed mid-run is recorded as failed when it is
            # picked up again, and the next request starts a new one.
            max_tries=1,
        )
    ]
    cron_jobs = maintenance_worker.cron_jobs
    redis_settings = maintenance_worker.redis_settings
    on_startup = maintenance_worker.on_startup
    on_shutdown = maintenance_worker.on_shutdown
    retry_jobs = maintenance_worker.retry_jobs
    job_serializer = maintenance_worker.job_serializer
    job_deserializer = maintenance_worker.job_deserializer
    job_timeout = settings.task_maintenance_timeout_seconds
    # A job killed mid-run is picked up again when its in-progress marker expires
    # and, past its tries, recorded as failed with this worker-level value, not
    # the job's own keep_result; so is a job this worker cannot run. A kept
    # result under the webhook outbox job's fixed key would refuse every request
    # for it until it expired (an hour by default). Nothing reads these results.
    keep_result = 0
    max_jobs = settings.task_maintenance_max_jobs
    queue_name = settings.task_maintenance_queue
    expires_extra_ms = maintenance_worker.expires_extra_ms
    health_check_interval = maintenance_worker.health_check_interval
    allow_abort_jobs = maintenance_worker.allow_abort_jobs
    job_completion_wait = maintenance_worker.job_completion_wait
    after_job_end = maintenance_worker.after_job_end
