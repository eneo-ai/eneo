from eneo.apps.app_runs.api.app_run_worker import worker as app_worker
from eneo.completion_models.infrastructure.model_cleanup_worker import (
    worker as model_cleanup_worker,
)
from eneo.crawler.python_engine import cleanup_orphaned_crawl_directories
from eneo.data_retention.infrastructure.data_retention_worker import (
    worker as data_retention_worker,
)
from eneo.embedding_models.infrastructure.embedding_model_cleanup_worker import (
    worker as embedding_model_cleanup_worker,
)
from eneo.integration.infrastructure.sharepoint_subscription_worker import (
    worker as sharepoint_subscription_worker,
)
from eneo.integration.tasks.integration_task import worker as integration_worker
from eneo.jobs.job_manager import CRAWLER_QUEUE_NAME, DEFAULT_QUEUE_NAME
from eneo.main.logging import get_logger
from eneo.transcription_models.infrastructure.transcription_model_cleanup_worker import (  # noqa: E501
    worker as transcription_model_cleanup_worker,
)
from eneo.worker.routes import crawler_worker
from eneo.worker.routes import worker as sub_worker
from eneo.worker.worker import ARQContext, Worker

logger = get_logger(__name__)

worker = Worker()
worker.include_subworker(sub_worker)
worker.include_subworker(app_worker)
worker.include_subworker(integration_worker)
worker.include_subworker(data_retention_worker)
worker.include_subworker(sharepoint_subscription_worker)
worker.include_subworker(model_cleanup_worker)
worker.include_subworker(transcription_model_cleanup_worker)
worker.include_subworker(embedding_model_cleanup_worker)


def _arq_settings(runtime: Worker, *, queue_name: str) -> dict[str, object]:
    """Return settings in the concrete mapping shape consumed by ARQ."""
    return {
        "functions": runtime.functions,
        "cron_jobs": runtime.cron_jobs,
        "redis_settings": runtime.redis_settings,
        "on_startup": runtime.on_startup,
        "on_shutdown": runtime.on_shutdown,
        "retry_jobs": runtime.retry_jobs,
        "job_serializer": runtime.job_serializer,
        "job_deserializer": runtime.job_deserializer,
        "job_timeout": runtime.job_timeout,
        "max_jobs": runtime.max_jobs,
        "expires_extra_ms": runtime.expires_extra_ms,
        "health_check_interval": runtime.health_check_interval,
        "allow_abort_jobs": runtime.allow_abort_jobs,
        "job_completion_wait": runtime.job_completion_wait,
        "after_job_end": runtime.after_job_end,
        "queue_name": queue_name,
    }


async def _crawler_worker_startup(ctx: ARQContext) -> None:
    removed = cleanup_orphaned_crawl_directories()
    await crawler_worker.startup(ctx)
    logger.info(
        "Crawler temporary workspace recovery completed",
        extra={"directories_removed": removed},
    )


# These public names are imported by the ARQ CLI. Dictionaries are deliberate:
# ARQ only reads attributes defined directly on a settings class, not inherited ones.
WorkerSettings = _arq_settings(worker, queue_name=DEFAULT_QUEUE_NAME)
CrawlerWorkerSettings = _arq_settings(
    crawler_worker,
    queue_name=CRAWLER_QUEUE_NAME,
)
CrawlerWorkerSettings["on_startup"] = _crawler_worker_startup
