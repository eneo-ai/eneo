from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from eneo.database.transaction_callbacks import after_outer_transaction
from eneo.jobs.job_manager import job_manager
from eneo.jobs.job_models import Task
from eneo.main.logging import get_logger
from eneo.websites.application.crawl_dispatch import reconcile_crawl_work
from eneo.websites.crawl_dependencies.crawl_models import CrawlTask
from eneo.websites.domain.crawl_run import (
    CrawlOrigin,
    CrawlPhase,
    CrawlRun,
)

if TYPE_CHECKING:
    from eneo.jobs.job_service import JobService
    from eneo.websites.domain.crawl_run_repo import CrawlRunRepository
    from eneo.websites.domain.website import Website

logger = get_logger(__name__)
_RECONCILIATION_CALLBACK_KEY = "crawler_reconciliation_after_commit"


class CrawlService:
    """Atomically coalesce and persist one durable crawl admission."""

    def __init__(
        self,
        repo: "CrawlRunRepository",
        job_service: "JobService",
    ) -> None:
        self.repo = repo
        self.job_service = job_service

    async def crawl(
        self,
        website: "Website",
        origin: CrawlOrigin = CrawlOrigin.MANUAL,
        *,
        reconcile_after_commit: bool = True,
    ) -> CrawlRun:
        run, created = await self.repo.add_or_get_active(
            CrawlRun.create(website=website, origin=origin)
        )
        if not created:
            return run

        assert run.id is not None
        attempt_id = uuid4()
        task = CrawlTask(
            schema_version=1,
            attempt_id=attempt_id,
            attempt_number=1,
            user_id=self.job_service.user.id,
            website_id=website.id,
            run_id=run.id,
            url=website.url,
            download_files=website.download_files,
            crawl_type=website.crawl_type,
            origin=origin,
        )
        job = await self.job_service.queue_job(
            Task.CRAWL,
            name=website.name or website.url,
            task_params=task,
            enqueue=False,
        )
        await self.repo.add_attempt(
            run_id=run.id,
            attempt_id=attempt_id,
            dispatch_id=job.id,
            task=task,
        )

        if reconcile_after_commit:
            self.schedule_reconciliation_after_commit()
        return await self.repo.one(run.id)

    def schedule_reconciliation_after_commit(self) -> None:
        """Request one crawl reconciliation for the surrounding transaction."""
        session = self.repo.session.sync_session
        transaction = session.get_transaction()
        if transaction is None:
            raise RuntimeError("Crawl reconciliation requires an active transaction")
        if session.info.get(_RECONCILIATION_CALLBACK_KEY) is transaction:
            return
        session.info[_RECONCILIATION_CALLBACK_KEY] = transaction

        def clear_registration() -> None:
            if session.info.get(_RECONCILIATION_CALLBACK_KEY) is transaction:
                session.info.pop(_RECONCILIATION_CALLBACK_KEY, None)

        async def reconcile_after_commit() -> None:
            clear_registration()
            try:
                await reconcile_crawl_work()
            except Exception:
                logger.exception(
                    "Immediate crawl reconciliation failed; scheduled repair will retry"
                )

        after_outer_transaction(
            session,
            on_commit=reconcile_after_commit,
            on_rollback=clear_registration,
        )

    async def cancel(self, run_id: UUID) -> CrawlRun:
        """Persist a stop request and signal its Redis delivery after commit."""
        cancellation = await self.repo.request_cancel(run_id)
        run = cancellation.run
        dispatch_id = cancellation.dispatch_id
        if dispatch_id is None or run.cancel_requested_at is None:
            return run

        if run.phase == CrawlPhase.TERMINAL:
            self.schedule_reconciliation_after_commit()
            return run

        async def stop_after_commit() -> None:
            try:
                await job_manager.signal_crawl_abort(dispatch_id)
            except Exception:
                logger.exception(
                    "Crawler abort signal failed; the persisted stop request will "
                    "revoke the worker lease",
                    extra={
                        "crawl_run_id": str(run.id),
                        "job_id": str(dispatch_id),
                    },
                )

        after_outer_transaction(
            self.repo.session.sync_session,
            on_commit=stop_after_commit,
        )
        return run
