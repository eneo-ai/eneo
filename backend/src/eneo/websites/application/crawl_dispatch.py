from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from arq.jobs import Job as ArqJob
from pydantic import ValidationError

from eneo.database.database import sessionmanager
from eneo.jobs.job_manager import job_manager
from eneo.jobs.job_models import Task
from eneo.main.config import get_settings
from eneo.main.logging import get_logger
from eneo.websites.crawl_dependencies.crawl_models import CrawlTask
from eneo.websites.domain.crawl_run import CrawlFailureCode
from eneo.websites.domain.crawl_run_repo import (
    CrawlDispatchCandidate,
    CrawlRunRepository,
)

logger = get_logger(__name__)
DISPATCH_RETRY_AFTER = timedelta(minutes=1)
QUEUE_REDELIVERY_AFTER = timedelta(minutes=5)
EnqueueCrawl = Callable[[Task, UUID, CrawlTask], Awaitable[ArqJob | None]]
DiscardCrawlDeliveries = Callable[[tuple[UUID, ...]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class CrawlReconciliationResult:
    interrupted: int
    claimed: int
    dispatched: int
    invalid: int
    delivery_errors: int


def _validate_candidate(candidate: CrawlDispatchCandidate) -> CrawlTask:
    task = CrawlTask.model_validate(candidate.payload)
    if (
        task.attempt_id != candidate.attempt_id
        or task.attempt_number != candidate.attempt_number
        or task.run_id != candidate.run_id
        or task.website_id != candidate.website_id
        or task.origin.value != candidate.origin
    ):
        raise ValueError("persisted crawl dispatch identity does not match its owners")
    return task


async def reconcile_crawl_work(
    *,
    enqueue: EnqueueCrawl = job_manager.enqueue,
    discard: DiscardCrawlDeliveries = job_manager.discard_crawl_deliveries,
    concurrency_limit: int | None = None,
) -> CrawlReconciliationResult:
    """Repair leases and deliver one fair, bounded batch to the crawl queue."""
    async with sessionmanager.session() as session, session.begin():
        repository = CrawlRunRepository(session)
        interrupted = await repository.interrupt_expired_attempts()
        cleanup_dispatch_ids = await repository.pending_transport_cleanup_candidates()

    delivery_errors = 0
    if cleanup_dispatch_ids:
        try:
            await discard(cleanup_dispatch_ids)
        except Exception:
            delivery_errors += 1
            logger.exception(
                "Expired crawl transport cleanup failed and will be retried",
                extra={"dispatch_count": len(cleanup_dispatch_ids)},
            )
        else:
            try:
                async with sessionmanager.session() as session, session.begin():
                    await CrawlRunRepository(session).acknowledge_transport_cleanup(
                        cleanup_dispatch_ids
                    )
            except Exception:
                delivery_errors += 1
                logger.exception(
                    "Expired crawl transport cleanup could not be acknowledged",
                    extra={"dispatch_count": len(cleanup_dispatch_ids)},
                )

    limit = (
        concurrency_limit
        if concurrency_limit is not None
        else get_settings().effective_crawl_job_concurrency_limit
    )
    async with sessionmanager.session() as session, session.begin():
        candidates = await CrawlRunRepository(session).claim_dispatch_candidates(
            concurrency_limit=limit,
            retry_after=DISPATCH_RETRY_AFTER,
            redeliver_after=QUEUE_REDELIVERY_AFTER,
        )

    dispatched = 0
    invalid = 0
    for candidate in candidates:
        try:
            task = _validate_candidate(candidate)
        except (ValidationError, ValueError) as exc:
            async with sessionmanager.session() as session, session.begin():
                rejected = await CrawlRunRepository(session).reject_pending_attempt(
                    candidate.attempt_id,
                    failure_code=CrawlFailureCode.INVALID_DISPATCH,
                    failure_detail="Stored crawl dispatch data is invalid",
                )
            invalid += int(rejected)
            logger.warning(
                "Rejected invalid persisted crawl dispatch",
                extra={
                    "attempt_id": str(candidate.attempt_id),
                    "run_id": str(candidate.run_id),
                    "reason": str(exc)[:512],
                },
            )
            continue

        try:
            await enqueue(Task.CRAWL, candidate.dispatch_id, task)
        except Exception:
            delivery_errors += 1
            logger.exception(
                "Crawl delivery failed; the durable attempt remains repairable",
                extra={
                    "attempt_id": str(candidate.attempt_id),
                    "run_id": str(candidate.run_id),
                    "job_id": str(candidate.dispatch_id),
                },
            )
            continue

        async with sessionmanager.session() as session, session.begin():
            marked = await CrawlRunRepository(session).mark_dispatched(
                candidate.attempt_id
            )
        dispatched += int(marked)

    return CrawlReconciliationResult(
        interrupted=interrupted,
        claimed=len(candidates),
        dispatched=dispatched,
        invalid=invalid,
        delivery_errors=delivery_errors,
    )
