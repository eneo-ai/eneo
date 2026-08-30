from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

from arq.worker import Function, create_worker

from eneo.jobs.job_manager import CRAWLER_QUEUE_NAME, DEFAULT_QUEUE_NAME
from eneo.main.config import get_settings
from eneo.websites.application.crawl_dispatch import CrawlReconciliationResult
from eneo.worker import routes as worker_routes
from eneo.worker.arq import CrawlerWorkerSettings, WorkerSettings
from eneo.worker.worker import _job_id_from_ctx


def _function_names(functions: list[Callable[..., Any] | Function]) -> set[str]:
    return {
        item.name if isinstance(item, Function) else item.__name__ for item in functions
    }


def test_general_and_crawler_workers_have_disjoint_registration() -> None:
    general_functions = _function_names(WorkerSettings["functions"])
    crawler_functions = _function_names(CrawlerWorkerSettings["functions"])

    assert "crawl" not in general_functions
    assert crawler_functions == {"crawl"}
    assert CrawlerWorkerSettings["cron_jobs"] == []
    assert WorkerSettings["queue_name"] == DEFAULT_QUEUE_NAME
    assert CrawlerWorkerSettings["queue_name"] == CRAWLER_QUEUE_NAME


def test_arq_constructs_crawler_with_shared_runtime_settings() -> None:
    general = create_worker(WorkerSettings)
    crawler = create_worker(CrawlerWorkerSettings)

    assert crawler.redis_settings == general.redis_settings
    assert crawler.retry_jobs == general.retry_jobs is False
    assert crawler.job_timeout_s == general.job_timeout_s
    assert crawler.max_jobs == get_settings().worker_max_jobs
    assert crawler.health_check_interval == general.health_check_interval
    assert crawler._job_completion_wait == general._job_completion_wait
    assert crawler.allow_abort_jobs == general.allow_abort_jobs is True
    assert crawler.on_startup is not None
    assert crawler.on_shutdown is not None
    assert crawler.after_job_end is not None
    assert crawler.job_serializer is general.job_serializer
    assert crawler.job_deserializer is general.job_deserializer
    assert crawler.functions["crawl"].keep_result_s == 0


async def test_successful_reconciliation_renews_its_health_signal(monkeypatch) -> None:
    result = CrawlReconciliationResult(
        interrupted=0,
        claimed=1,
        dispatched=1,
        invalid=0,
        delivery_errors=0,
    )
    reconcile = AsyncMock(return_value=result)
    mark_healthy = AsyncMock()
    monkeypatch.setattr(worker_routes, "reconcile_crawl_work", reconcile)
    monkeypatch.setattr(
        worker_routes,
        "mark_crawl_reconciliation_healthy",
        mark_healthy,
    )

    assert await worker_routes._reconcile_crawl_dispatch_and_record_health() == result
    mark_healthy.assert_awaited_once_with()


async def test_delivery_error_does_not_renew_reconciliation_health(monkeypatch) -> None:
    result = CrawlReconciliationResult(
        interrupted=0,
        claimed=1,
        dispatched=0,
        invalid=0,
        delivery_errors=1,
    )
    monkeypatch.setattr(
        worker_routes,
        "reconcile_crawl_work",
        AsyncMock(return_value=result),
    )
    mark_healthy = AsyncMock()
    monkeypatch.setattr(
        worker_routes,
        "mark_crawl_reconciliation_healthy",
        mark_healthy,
    )

    assert await worker_routes._reconcile_crawl_dispatch_and_record_health() == result
    mark_healthy.assert_not_awaited()


def test_job_id_from_ctx_returns_uuid_from_uuid_value():
    job_id = uuid4()

    assert _job_id_from_ctx({"job_id": job_id}) == job_id


def test_job_id_from_ctx_parses_uuid_strings():
    job_id = uuid4()

    assert _job_id_from_ctx({"job_id": str(job_id)}) == job_id


def test_job_id_from_ctx_returns_none_for_invalid_ids():
    assert _job_id_from_ctx({"job_id": "arq:cron:job"}) is None
