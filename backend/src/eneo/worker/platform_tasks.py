from __future__ import annotations

from typing import cast
from uuid import UUID

from eneo.flows.flow_run_dispatch_request import FlowRunDispatchTaskKwargs
from eneo.flows.runtime.tasks import (
    deliver_flow_audit_outbox,
    deliver_flow_webhook_outbox,
    execute_flow_run_task,
    reconcile_expired_review_checkpoints,
    reconcile_stale_running_runs,
    redispatch_stale_queued_runs,
)
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.tasks.routing import (
    FLOW_DELIVER_AUDIT_OUTBOX_TASK,
    FLOW_DELIVER_WEBHOOK_OUTBOX_TASK,
    FLOW_EXECUTE_TASK,
    FLOW_RECONCILE_REVIEW_EXPIRY_TASK,
    FLOW_RECONCILE_RUNNING_TASK,
    FLOW_REDISPATCH_STALE_QUEUED_TASK,
)
from eneo.worker.worker import Worker

execution_worker = Worker(enable_feeder=False)
maintenance_worker = Worker(enable_feeder=False)


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
    second=0,
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
    name=FLOW_DELIVER_AUDIT_OUTBOX_TASK,
    second=0,
    keep_result=60,
)
async def deliver_audit_outbox(*, container: Container) -> dict[str, int | str]:
    del container
    return await deliver_flow_audit_outbox()


@maintenance_worker.cron_job(
    manages_own_session=True,
    name=FLOW_DELIVER_WEBHOOK_OUTBOX_TASK,
    second={0, 30},
    keep_result=60,
)
async def deliver_webhook_outbox(*, container: Container) -> dict[str, int | str]:
    del container
    return await deliver_flow_webhook_outbox()


class PlatformExecutionWorkerSettings:
    settings = get_settings()
    functions = execution_worker.functions
    cron_jobs: list[object] = []
    redis_settings = execution_worker.redis_settings
    on_startup = execution_worker.on_startup
    on_shutdown = execution_worker.on_shutdown
    retry_jobs = execution_worker.retry_jobs
    job_serializer = execution_worker.job_serializer
    job_deserializer = execution_worker.job_deserializer
    job_timeout = settings.task_execution_timeout_seconds
    max_jobs = settings.task_execution_max_jobs
    queue_name = settings.task_execution_queue
    expires_extra_ms = execution_worker.expires_extra_ms
    health_check_interval = execution_worker.health_check_interval
    allow_abort_jobs = execution_worker.allow_abort_jobs
    job_completion_wait = execution_worker.job_completion_wait
    after_job_end = execution_worker.after_job_end


class PlatformMaintenanceWorkerSettings:
    settings = get_settings()
    functions: list[object] = []
    cron_jobs = maintenance_worker.cron_jobs
    redis_settings = maintenance_worker.redis_settings
    on_startup = maintenance_worker.on_startup
    on_shutdown = maintenance_worker.on_shutdown
    retry_jobs = maintenance_worker.retry_jobs
    job_serializer = maintenance_worker.job_serializer
    job_deserializer = maintenance_worker.job_deserializer
    job_timeout = settings.task_maintenance_timeout_seconds
    max_jobs = settings.task_maintenance_max_jobs
    queue_name = settings.task_maintenance_queue
    expires_extra_ms = maintenance_worker.expires_extra_ms
    health_check_interval = maintenance_worker.health_check_interval
    allow_abort_jobs = maintenance_worker.allow_abort_jobs
    job_completion_wait = maintenance_worker.job_completion_wait
    after_job_end = maintenance_worker.after_job_end
