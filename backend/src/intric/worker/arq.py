from intric.apps.app_runs.api.app_run_worker import worker as app_worker
from intric.data_retention.infrastructure.data_retention_worker import (
    worker as data_retention_worker,
)
from intric.integration.tasks.integration_task import worker as integration_worker
from intric.worker.routes import worker as sub_worker
from intric.worker.worker import Worker

worker = Worker()
worker.include_subworker(sub_worker)
worker.include_subworker(app_worker)
worker.include_subworker(integration_worker)
worker.include_subworker(data_retention_worker)


class WorkerSettings:
    functions = worker.functions
    cron_jobs = worker.cron_jobs
    redis_settings = worker.redis_settings
    on_startup = worker.on_startup
    on_shutdown = worker.on_shutdown
    retry_jobs = worker.retry_jobs
    job_timeout = worker.job_timeout
    max_jobs = worker.max_jobs
    expires_extra_ms = worker.expires_extra_ms

    # Health check interval: How often ARQ updates the health key in Redis
    # Default is 3600s (1 hour), we use 60s for faster health visibility
    health_check_interval = worker.health_check_interval

    # Allow job.abort() for preemption of stale jobs
    allow_abort_jobs = worker.allow_abort_jobs

    # Time to wait for jobs to complete on graceful shutdown
    job_completion_wait = worker.job_completion_wait

    # ARQ lifecycle hooks for job observability
    # NOTE: on_job_start removed - conflicts with mark_job_started() CAS check
    after_job_end = worker.after_job_end
