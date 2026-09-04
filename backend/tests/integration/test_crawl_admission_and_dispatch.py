import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock, call
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from eneo.audit.application import audit_service as audit_service_module
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.outcome import Outcome
from eneo.crawler.engine import (
    ConditionalGet,
    CrawlEvent,
    CrawlFinished,
    CrawlRequest,
    FileDownloaded,
    FileFailed,
    PageCrawled,
    PageFailed,
    PageUnchanged,
)
from eneo.database.database import AsyncSession, sessionmanager
from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.info_blobs_table import (
    InfoBlobs,
    InfoBlobVersionState,
)
from eneo.database.tables.job_table import Jobs
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.database.tables.websites_table import CrawlAttempts
from eneo.database.tables.websites_table import CrawlRuns as CrawlRunsTable
from eneo.database.tables.websites_table import Websites as WebsitesTable
from eneo.jobs.job_models import Task
from eneo.jobs.job_repo import JobRepository
from eneo.jobs.job_service import JobService
from eneo.main.container.container import Container, SessionProxy
from eneo.main.models import Status
from eneo.users.user import UserInDB
from eneo.websites.application import crawl_dispatch
from eneo.websites.crawl_dependencies.crawl_models import CrawlTask
from eneo.websites.domain import crawl_service as crawl_service_module
from eneo.websites.domain.crawl_run import (
    CrawlFailureCode,
    CrawlOrigin,
    CrawlOutcome,
    CrawlPhase,
    CrawlType,
)
from eneo.websites.domain.crawl_run_repo import CrawlRunRepository
from eneo.websites.domain.crawl_service import CrawlService
from eneo.websites.domain.website import UpdateInterval, Website
from eneo.worker import crawl_tasks as crawl_tasks_module
from eneo.worker.crawl import CrawlLeaseLostError
from eneo.worker.crawl_tasks import crawl_task

pytestmark = pytest.mark.integration


class _EmptyCrawlEngine:
    async def crawl(self, request: CrawlRequest) -> AsyncIterator[CrawlEvent]:
        del request
        yield CrawlFinished(
            status="completed",
            pages_crawled=0,
            pages_failed=0,
        )


class _AuthoritativeEmptySitemapEngine:
    async def crawl(self, request: CrawlRequest) -> AsyncIterator[CrawlEvent]:
        del request
        yield CrawlFinished(
            status="completed",
            pages_crawled=0,
            pages_failed=0,
            sitemap_fingerprint=sha256(b"").hexdigest(),
            sitemap_entries=0,
        )


class _StructurallyIncompleteSitemapEngine:
    async def crawl(self, request: CrawlRequest) -> AsyncIterator[CrawlEvent]:
        yield PageUnchanged(url=request.url)
        yield PageFailed(url=request.url, reason="invalid_sitemap")
        yield CrawlFinished(
            status="completed",
            pages_crawled=0,
            pages_failed=1,
            pages_unchanged=1,
        )


class _BlockedCrawlEngine:
    async def crawl(self, request: CrawlRequest) -> AsyncIterator[CrawlEvent]:
        yield PageFailed(
            url=request.url,
            reason="http_403",
            status_code=403,
        )
        yield CrawlFinished(
            status="completed",
            pages_crawled=0,
            pages_failed=1,
        )


class _SinglePageCrawlEngine:
    async def crawl(self, request: CrawlRequest) -> AsyncIterator[CrawlEvent]:
        yield PageCrawled(
            url=request.url,
            title="Page",
            content="<main>Page content</main>",
            etag=None,
            last_modified=None,
        )
        yield CrawlFinished(
            status="completed",
            pages_crawled=1,
            pages_failed=0,
        )


class _ConditionalFileCrawlEngine:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.request: CrawlRequest | None = None

    async def crawl(self, request: CrawlRequest) -> AsyncIterator[CrawlEvent]:
        self.request = request
        if request.conditional_gets:
            for validator in request.conditional_gets:
                yield PageUnchanged(url=validator.url)
            yield CrawlFinished(
                status=(
                    "partial" if request.conditional_gets_truncated else "completed"
                ),
                pages_crawled=0,
                pages_failed=0,
                pages_unchanged=len(request.conditional_gets),
                reason=("item_limit" if request.conditional_gets_truncated else None),
            )
            return

        yield PageCrawled(
            url=request.url,
            title="Page",
            content="<main>Page content</main>",
            etag='"page-v1"',
            last_modified=None,
        )
        yield FileDownloaded(
            url=f"{request.url}/guide.pdf",
            filename=self.file_path.name,
            path=self.file_path,
        )
        yield CrawlFinished(
            status="completed",
            pages_crawled=1,
            pages_failed=0,
            files_downloaded=1,
        )


class _PageLimitedCrawlEngine:
    async def crawl(self, request: CrawlRequest) -> AsyncIterator[CrawlEvent]:
        yield PageUnchanged(url=request.url)
        yield CrawlFinished(
            status="partial",
            pages_crawled=0,
            pages_failed=0,
            pages_unchanged=1,
            reason="page_limit",
        )


class _FailureDominatedPartialCrawlEngine:
    async def crawl(self, request: CrawlRequest) -> AsyncIterator[CrawlEvent]:
        yield PageUnchanged(url=request.url)
        yield PageFailed(
            url=f"{request.url}/unavailable",
            reason="http_503",
            status_code=503,
            retryable=True,
        )
        yield CrawlFinished(
            status="completed",
            pages_crawled=0,
            pages_failed=1,
            pages_unchanged=1,
        )


class _UsefulPartialCrawlEngine:
    async def crawl(self, request: CrawlRequest) -> AsyncIterator[CrawlEvent]:
        yield PageUnchanged(url=request.url)
        yield PageUnchanged(url=f"{request.url}/useful")
        yield PageFailed(
            url=f"{request.url}/redirected",
            reason="redirect_rejected",
        )
        yield CrawlFinished(
            status="completed",
            pages_crawled=0,
            pages_failed=1,
            pages_unchanged=2,
        )


class _UsefulFilePartialCrawlEngine:
    def __init__(self, paths: tuple[Path, Path]) -> None:
        self.paths = paths

    async def crawl(self, request: CrawlRequest) -> AsyncIterator[CrawlEvent]:
        for path in self.paths:
            yield FileDownloaded(
                url=f"{request.url}/{path.name}",
                filename=path.name,
                path=path,
            )
        yield FileFailed(
            url=f"{request.url}/unavailable.pdf",
            reason="http_503",
            status_code=503,
            retryable=True,
        )
        yield CrawlFinished(
            status="completed",
            pages_crawled=0,
            pages_failed=0,
            files_downloaded=2,
            files_failed=1,
        )


class _CloseTrackingCrawlStream:
    def __init__(self, request: CrawlRequest, path: Path) -> None:
        self._request = request
        self._path = path
        self._yielded = False
        self._never_finishes = asyncio.Event()
        self.closed = False

    def __aiter__(self) -> "_CloseTrackingCrawlStream":
        return self

    async def __anext__(self) -> CrawlEvent:
        if not self._yielded:
            self._yielded = True
            return FileDownloaded(
                url=f"{self._request.url}/{self._path.name}",
                filename=self._path.name,
                path=self._path,
            )
        await self._never_finishes.wait()
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True


class _CloseTrackingCrawlEngine:
    def __init__(self, path: Path) -> None:
        self._path = path
        self.stream: _CloseTrackingCrawlStream | None = None

    def crawl(self, request: CrawlRequest) -> _CloseTrackingCrawlStream:
        self.stream = _CloseTrackingCrawlStream(request, self._path)
        return self.stream


class _FailureDominatedPageLimitedCrawlEngine:
    async def crawl(self, request: CrawlRequest) -> AsyncIterator[CrawlEvent]:
        yield PageUnchanged(url=request.url)
        for index in range(3):
            yield PageFailed(
                url=f"{request.url}/unavailable-{index}",
                reason="http_503",
                status_code=503,
                retryable=True,
            )
        yield CrawlFinished(
            status="partial",
            pages_crawled=0,
            pages_failed=3,
            pages_unchanged=1,
            reason="page_limit",
        )


async def _persist_website(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    label: str,
    crawl_type: CrawlType = CrawlType.CRAWL,
    download_files: bool = False,
) -> Website:
    embedding_model_id = await session.scalar(sa.select(EmbeddingModels.id).limit(1))
    assert embedding_model_id is not None
    record = WebsitesTable(
        name=label,
        url=f"https://{label.lower().replace(' ', '-')}.example.com",
        download_files=download_files,
        crawl_type=crawl_type,
        update_interval=UpdateInterval.NEVER,
        size=0,
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
        space_id=None,
    )
    session.add(record)
    await session.flush()
    return cast(
        Website,
        SimpleNamespace(
            id=record.id,
            tenant_id=tenant_id,
            user_id=user_id,
            name=record.name,
            url=record.url,
            download_files=record.download_files,
            crawl_type=record.crawl_type,
        ),
    )


def _user(user_id: UUID, tenant_id: UUID) -> UserInDB:
    return cast(UserInDB, SimpleNamespace(id=user_id, tenant_id=tenant_id))


async def _admit(
    session: AsyncSession,
    *,
    website: Website,
    user: UserInDB,
    origin: CrawlOrigin = CrawlOrigin.MANUAL,
    reconcile_after_commit: bool = False,
):
    return await CrawlService(
        CrawlRunRepository(session),
        JobService(user, JobRepository(session)),
    ).crawl(
        website,
        origin,
        reconcile_after_commit=reconcile_after_commit,
    )


async def _default_identity(session: AsyncSession, admin_user) -> tuple[UUID, UUID]:
    return admin_user.tenant_id, admin_user.id


async def test_outer_rollback_publishes_nothing(
    db_session,
    admin_user,
    monkeypatch,
) -> None:
    async with db_session() as session:
        tenant_id, user_id = await _default_identity(session, admin_user)
        website = await _persist_website(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            label="Rollback crawl",
        )

    reconcile = AsyncMock()
    monkeypatch.setattr(crawl_service_module, "reconcile_crawl_work", reconcile)
    async with sessionmanager.session() as session:
        transaction = await session.begin()
        await _admit(
            session,
            website=website,
            user=admin_user,
            reconcile_after_commit=True,
        )
        await transaction.rollback()
    await asyncio.sleep(0)

    reconcile.assert_not_awaited()
    async with db_session() as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(CrawlRunsTable)
                .where(CrawlRunsTable.website_id == website.id)
            )
            == 0
        )


async def test_outer_commit_requests_immediate_reconciliation(
    db_session,
    admin_user,
    monkeypatch,
) -> None:
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Committed crawl",
        )

    reconcile = AsyncMock()
    monkeypatch.setattr(crawl_service_module, "reconcile_crawl_work", reconcile)
    async with sessionmanager.session() as session, session.begin():
        await _admit(
            session,
            website=website,
            user=admin_user,
            reconcile_after_commit=True,
        )
    for _ in range(5):
        if reconcile.await_count:
            break
        await asyncio.sleep(0)

    reconcile.assert_awaited_once_with()


async def test_reconciliation_is_coalesced_per_transaction(
    admin_user,
    monkeypatch,
) -> None:
    reconcile = AsyncMock()
    monkeypatch.setattr(crawl_service_module, "reconcile_crawl_work", reconcile)

    async with sessionmanager.session() as session, session.begin():
        service = CrawlService(
            CrawlRunRepository(session),
            JobService(admin_user, JobRepository(session)),
        )
        service.schedule_reconciliation_after_commit()
        service.schedule_reconciliation_after_commit()

    for _ in range(5):
        if reconcile.await_count:
            break
        await asyncio.sleep(0)

    reconcile.assert_awaited_once_with()


async def test_reconciliation_is_not_coalesced_across_transactions(
    admin_user,
    monkeypatch,
) -> None:
    reconcile = AsyncMock()
    monkeypatch.setattr(crawl_service_module, "reconcile_crawl_work", reconcile)

    async with sessionmanager.session() as session:
        service = CrawlService(
            CrawlRunRepository(session),
            JobService(admin_user, JobRepository(session)),
        )
        async with session.begin():
            service.schedule_reconciliation_after_commit()
        async with session.begin():
            service.schedule_reconciliation_after_commit()

    for _ in range(5):
        if reconcile.await_count == 2:
            break
        await asyncio.sleep(0)

    assert reconcile.await_count == 2


async def test_queued_cancellation_reconciles_delivery_after_commit(
    db_session,
    admin_user,
    monkeypatch,
) -> None:
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Cancelled queued crawl",
        )
        run = await _admit(session, website=website, user=admin_user)
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        assert await CrawlRunRepository(session).mark_dispatched(attempt.id)

    discard = AsyncMock()
    reconcile = AsyncMock()
    monkeypatch.setattr(
        crawl_service_module.job_manager,
        "discard_crawl_deliveries",
        discard,
    )
    monkeypatch.setattr(crawl_service_module, "reconcile_crawl_work", reconcile)

    async with sessionmanager.session() as session, session.begin():
        cancellation = await CrawlService(
            CrawlRunRepository(session),
            JobService(admin_user, JobRepository(session)),
        ).cancel(cast(UUID, run.id))
        assert cancellation.phase == CrawlPhase.TERMINAL
        assert cancellation.outcome == CrawlOutcome.CANCELLED
        discard.assert_not_awaited()

    for _ in range(5):
        if reconcile.await_count:
            break
        await asyncio.sleep(0)

    discard.assert_not_awaited()
    reconcile.assert_awaited_once_with()


async def test_running_cancellation_signals_worker_only_after_commit(
    db_session,
    admin_user,
    monkeypatch,
) -> None:
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Cancelled running crawl",
        )
        run = await _admit(session, website=website, user=admin_user)
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        dispatch_id = attempt.dispatch_id
        repository = CrawlRunRepository(session)
        assert await repository.mark_dispatched(attempt.id)
        assert await repository.claim_attempt(
            attempt.id,
            dispatch_id=dispatch_id,
            lease_owner="cancellable-worker",
            lease_duration=timedelta(minutes=5),
        )

    signal = AsyncMock()
    monkeypatch.setattr(
        crawl_service_module.job_manager,
        "signal_crawl_abort",
        signal,
    )

    async with sessionmanager.session() as session, session.begin():
        cancellation = await CrawlService(
            CrawlRunRepository(session),
            JobService(admin_user, JobRepository(session)),
        ).cancel(cast(UUID, run.id))
        assert cancellation.phase == CrawlPhase.STOPPING
        signal.assert_not_awaited()

    for _ in range(5):
        if signal.await_count:
            break
        await asyncio.sleep(0)

    signal.assert_awaited_once_with(dispatch_id)


async def test_concurrent_admission_coalesces_one_run_job_and_attempt(
    db_session,
    admin_user,
) -> None:
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Concurrent crawl",
        )

    async def admit_once():
        async with sessionmanager.session() as session, session.begin():
            return await _admit(
                session,
                website=website,
                user=admin_user,
            )

    first, second = await asyncio.gather(admit_once(), admit_once())

    assert first.id == second.id
    async with db_session() as session:
        run_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(CrawlRunsTable)
            .where(CrawlRunsTable.website_id == website.id)
        )
        attempt_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(CrawlAttempts)
            .join(CrawlRunsTable, CrawlRunsTable.id == CrawlAttempts.crawl_run_id)
            .where(CrawlRunsTable.website_id == website.id)
        )
        crawl_job_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(Jobs)
            .join(CrawlRunsTable, CrawlRunsTable.job_id == Jobs.id)
            .where(CrawlRunsTable.website_id == website.id)
            .where(Jobs.task == Task.CRAWL.value)
        )
    assert (run_count, attempt_count, crawl_job_count) == (1, 1, 1)


async def test_website_deletion_fence_prevents_late_crawl_admission(
    db_session,
    admin_user,
) -> None:
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Deletion admission fence",
        )

    async def admit_while_deletion_is_locked():
        async with sessionmanager.session() as session, session.begin():
            return await _admit(session, website=website, user=admin_user)

    admission_task = None
    async with sessionmanager.session() as session, session.begin():
        assert (
            await CrawlRunRepository(session).lock_website_deletion(website.id) is None
        )
        admission_task = asyncio.create_task(admit_while_deletion_is_locked())
        await asyncio.sleep(0.1)
        assert not admission_task.done()
        await session.execute(
            sa.delete(WebsitesTable).where(WebsitesTable.id == website.id)
        )

    assert admission_task is not None
    with pytest.raises(sa.exc.IntegrityError):
        await asyncio.wait_for(admission_task, timeout=5)


async def test_manual_admission_uses_the_authorized_initiating_user(
    db_session,
    admin_user,
    user_factory,
) -> None:
    async with db_session() as session:
        initiator = await user_factory(
            session,
            tenant_id=admin_user.tenant_id,
        )
        initiator_id = initiator.id
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Shared website crawl",
        )
        run = await _admit(
            session,
            website=website,
            user=_user(initiator_id, admin_user.tenant_id),
        )

        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        job = await session.get(Jobs, attempt.dispatch_id)
        assert job is not None
        task = CrawlTask.model_validate(attempt.dispatch_payload)
        task_user_id = task.user_id
        job_user_id = job.user_id

    assert task_user_id == initiator_id
    assert job_user_id == initiator_id


async def test_deleted_job_projection_does_not_invalidate_durable_dispatch(
    db_session,
    admin_user,
) -> None:
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Jobless dispatch",
        )
        run = await _admit(session, website=website, user=admin_user)
        record = await session.get(CrawlRunsTable, run.id)
        assert record is not None
        job = await session.get(Jobs, record.job_id)
        assert job is not None
        await session.delete(job)

    enqueue = AsyncMock(return_value=None)
    result = await crawl_dispatch.reconcile_crawl_work(
        enqueue=enqueue,
        concurrency_limit=1,
    )

    assert (result.claimed, result.invalid, result.dispatched) == (1, 0, 1)
    task = enqueue.await_args.args[2]
    assert task.website_id == website.id
    assert task.user_id == admin_user.id


async def test_delivery_failure_remains_repairable_and_retry_is_idempotent(
    db_session,
    admin_user,
) -> None:
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Repairable delivery",
        )
        run = await _admit(
            session,
            website=website,
            user=admin_user,
            origin=CrawlOrigin.SCHEDULED,
        )

    failed_enqueue = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
    first = await crawl_dispatch.reconcile_crawl_work(
        enqueue=failed_enqueue,
        concurrency_limit=1,
    )
    assert (first.claimed, first.dispatched, first.delivery_errors) == (1, 0, 1)

    async with db_session() as session:
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        assert attempt.dispatch_attempted_at is not None
        assert attempt.dispatched_at is None
        attempt.dispatch_attempted_at -= timedelta(minutes=2)

    duplicate_enqueue = AsyncMock(return_value=None)
    second = await crawl_dispatch.reconcile_crawl_work(
        enqueue=duplicate_enqueue,
        concurrency_limit=1,
    )
    assert (second.claimed, second.dispatched, second.delivery_errors) == (1, 1, 0)
    async with db_session() as session:
        reloaded = await CrawlRunRepository(session).one(cast(UUID, run.id))
        assert reloaded.phase == CrawlPhase.QUEUED
        assert reloaded.origin == CrawlOrigin.SCHEDULED
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        assert attempt.dispatch_attempted_at is not None
        assert attempt.dispatched_at is not None
        attempt.dispatch_attempted_at -= timedelta(minutes=6)
        attempt.dispatched_at -= timedelta(minutes=6)

    redelivered = await crawl_dispatch.reconcile_crawl_work(
        enqueue=duplicate_enqueue,
        concurrency_limit=1,
    )
    assert (redelivered.claimed, redelivered.dispatched) == (1, 1)


async def test_expired_worker_delivery_is_discarded_after_database_repair(
    db_session,
    admin_user,
) -> None:
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Expired transport delivery",
        )
        run = await _admit(session, website=website, user=admin_user)
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        run_id = cast(UUID, run.id)
        dispatch_id = attempt.dispatch_id
        repo = CrawlRunRepository(session)
        assert await repo.mark_dispatched(attempt.id) is True
        assert (
            await repo.claim_attempt(
                attempt.id,
                dispatch_id=dispatch_id,
                lease_owner="dead-worker",
                lease_duration=timedelta(minutes=5),
            )
            is not None
        )
        attempt.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    async def assert_repaired_before_discard(job_ids: tuple[UUID, ...]) -> None:
        assert job_ids == (dispatch_id,)
        async with db_session() as verification_session:
            repaired = await CrawlRunRepository(verification_session).one(run_id)
            assert repaired.phase == CrawlPhase.TERMINAL
            assert repaired.outcome == CrawlOutcome.INTERRUPTED

    discard = AsyncMock(side_effect=assert_repaired_before_discard)
    result = await crawl_dispatch.reconcile_crawl_work(
        enqueue=AsyncMock(return_value=None),
        discard=discard,
        concurrency_limit=1,
    )

    assert (result.interrupted, result.delivery_errors) == (1, 0)
    discard.assert_awaited_once_with((dispatch_id,))

    async with db_session() as session:
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.dispatch_id == dispatch_id)
        )
        assert attempt is not None
        assert attempt.transport_cleaned_at is not None


async def test_concurrent_reconcilers_cleanup_the_same_expired_delivery_safely(
    db_session,
    admin_user,
) -> None:
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Concurrent transport cleanup",
        )
        run = await _admit(session, website=website, user=admin_user)
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        dispatch_id = attempt.dispatch_id
        repository = CrawlRunRepository(session)
        assert await repository.mark_dispatched(attempt.id) is True
        assert (
            await repository.claim_attempt(
                attempt.id,
                dispatch_id=dispatch_id,
                lease_owner="dead-worker",
                lease_duration=timedelta(minutes=5),
            )
            is not None
        )
        attempt.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        assert await repository.interrupt_expired_attempts() == 1

    both_discards_started = asyncio.Event()
    discard_count = 0

    async def synchronize_discard(job_ids: tuple[UUID, ...]) -> None:
        nonlocal discard_count
        assert job_ids == (dispatch_id,)
        discard_count += 1
        if discard_count == 2:
            both_discards_started.set()
        await asyncio.wait_for(both_discards_started.wait(), timeout=5)

    first, second = await asyncio.wait_for(
        asyncio.gather(
            crawl_dispatch.reconcile_crawl_work(
                enqueue=AsyncMock(return_value=None),
                discard=synchronize_discard,
                concurrency_limit=1,
            ),
            crawl_dispatch.reconcile_crawl_work(
                enqueue=AsyncMock(return_value=None),
                discard=synchronize_discard,
                concurrency_limit=1,
            ),
        ),
        timeout=10,
    )

    assert first.interrupted == second.interrupted == 0
    assert first.delivery_errors == second.delivery_errors == 0
    assert discard_count == 2
    async with db_session() as session:
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.dispatch_id == dispatch_id)
        )
        assert attempt is not None
        assert attempt.transport_cleaned_at is not None


async def test_dispatch_reconciliation_waits_for_contended_owner_lock(
    db_session,
    admin_user,
) -> None:
    async with db_session() as session:
        first_website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Contended dispatch first",
        )
        second_website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Contended dispatch second",
        )
        await _admit(session, website=first_website, user=admin_user)
        await _admit(session, website=second_website, user=admin_user)

    enqueue = AsyncMock(return_value=None)
    reconcile_task: asyncio.Task[crawl_dispatch.CrawlReconciliationResult] | None = None
    try:
        async with sessionmanager.session() as lock_session, lock_session.begin():
            claimed_while_locked = await CrawlRunRepository(
                lock_session
            ).claim_dispatch_candidates(
                concurrency_limit=1,
                retry_after=crawl_dispatch.DISPATCH_RETRY_AFTER,
                redeliver_after=crawl_dispatch.QUEUE_REDELIVERY_AFTER,
            )
            assert len(claimed_while_locked) == 1

            reconcile_task = asyncio.create_task(
                crawl_dispatch.reconcile_crawl_work(
                    enqueue=enqueue,
                    discard=AsyncMock(),
                    concurrency_limit=2,
                )
            )
            await asyncio.sleep(0.1)
            assert not reconcile_task.done()

        result = await asyncio.wait_for(reconcile_task, timeout=5)
    finally:
        if reconcile_task is not None and not reconcile_task.done():
            reconcile_task.cancel()

    assert (result.claimed, result.dispatched, result.delivery_errors) == (1, 1, 0)
    enqueue.assert_awaited_once()


@pytest.mark.parametrize("cancel_requested", [False, True])
async def test_finished_worker_transport_cleanup_retries_until_acknowledged(
    db_session,
    admin_user,
    monkeypatch,
    *,
    cancel_requested: bool,
) -> None:
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Failed transport cleanup",
        )
        run = await _admit(session, website=website, user=admin_user)
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        dispatch_id = attempt.dispatch_id
        repo = CrawlRunRepository(session)
        assert await repo.mark_dispatched(attempt.id) is True
        assert (
            await repo.claim_attempt(
                attempt.id,
                dispatch_id=attempt.dispatch_id,
                lease_owner="dead-worker",
                lease_duration=timedelta(minutes=5),
            )
            is not None
        )
        if cancel_requested:
            assert (await repo.request_cancel(run.id)).run.phase == CrawlPhase.STOPPING
        attempt.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    original_acknowledge = CrawlRunRepository.acknowledge_transport_cleanup
    acknowledge_calls = 0

    async def acknowledge_after_one_failure(
        repository: CrawlRunRepository,
        dispatch_ids: tuple[UUID, ...],
    ) -> None:
        nonlocal acknowledge_calls
        acknowledge_calls += 1
        if acknowledge_calls == 1:
            raise ConnectionError("PostgreSQL acknowledgement interrupted")
        await original_acknowledge(repository, dispatch_ids)

    monkeypatch.setattr(
        CrawlRunRepository,
        "acknowledge_transport_cleanup",
        acknowledge_after_one_failure,
    )
    discard = AsyncMock(side_effect=[ConnectionError("Redis unavailable"), None, None])
    enqueue = AsyncMock(return_value=None)

    failed = await crawl_dispatch.reconcile_crawl_work(
        enqueue=enqueue,
        discard=discard,
        concurrency_limit=1,
    )

    async with db_session() as session:
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.dispatch_id == dispatch_id)
        )
        assert attempt is not None
        assert attempt.transport_cleaned_at is None
        assert (
            await CrawlRunRepository(session).health_snapshot()
        ).pending_transport_cleanup == 1

    acknowledgement_failed = await crawl_dispatch.reconcile_crawl_work(
        enqueue=enqueue,
        discard=discard,
        concurrency_limit=1,
    )

    async with db_session() as session:
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.dispatch_id == dispatch_id)
        )
        assert attempt is not None
        assert attempt.transport_cleaned_at is None

    retried = await crawl_dispatch.reconcile_crawl_work(
        enqueue=enqueue,
        discard=discard,
        concurrency_limit=1,
    )

    async with db_session() as session:
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.dispatch_id == dispatch_id)
        )
        assert attempt is not None
        assert attempt.transport_cleaned_at is not None
        assert (
            await CrawlRunRepository(session).health_snapshot()
        ).pending_transport_cleanup == 0

    converged = await crawl_dispatch.reconcile_crawl_work(
        enqueue=enqueue,
        discard=discard,
        concurrency_limit=1,
    )

    assert (failed.interrupted, failed.delivery_errors) == (1, 1)
    assert (
        acknowledgement_failed.interrupted,
        acknowledgement_failed.delivery_errors,
    ) == (
        0,
        1,
    )
    assert (retried.interrupted, retried.delivery_errors) == (0, 0)
    assert (converged.interrupted, converged.delivery_errors) == (0, 0)
    assert discard.await_args_list == [
        call((dispatch_id,)),
        call((dispatch_id,)),
        call((dispatch_id,)),
    ]


async def test_invalid_persisted_dispatch_becomes_terminal_failure(
    db_session,
    admin_user,
) -> None:
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Invalid dispatch",
        )
        run = await _admit(session, website=website, user=admin_user)
        await session.execute(
            sa.update(CrawlAttempts)
            .where(CrawlAttempts.crawl_run_id == run.id)
            .values(dispatch_payload={"schema_version": 1})
        )

    enqueue = AsyncMock()
    result = await crawl_dispatch.reconcile_crawl_work(
        enqueue=enqueue,
        concurrency_limit=1,
    )

    assert (result.claimed, result.invalid, result.dispatched) == (1, 1, 0)
    enqueue.assert_not_awaited()
    async with db_session() as session:
        reloaded = await CrawlRunRepository(session).one(cast(UUID, run.id))
        assert reloaded.phase == CrawlPhase.TERMINAL
        assert reloaded.outcome == CrawlOutcome.FAILED
        assert reloaded.failure_code == CrawlFailureCode.INVALID_DISPATCH.value
        job = await session.get(Jobs, reloaded.job_id)
        assert job is not None
        assert job.status == Status.FAILED.value


async def test_worker_persists_invalid_dispatch_rejection_after_claim_rollback(
    db_session,
    admin_user,
) -> None:
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Invalid worker dispatch",
        )
        run = await _admit(session, website=website, user=admin_user)
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        incoming_task = CrawlTask.model_validate(attempt.dispatch_payload)
        attempt_id = attempt.id
        dispatch_id = attempt.dispatch_id
        run_id = cast(UUID, run.id)
        attempt.dispatch_payload = {"schema_version": 1}

    with pytest.raises(ValueError):
        await crawl_task(
            job_id=dispatch_id,
            params=incoming_task,
            container=cast(Container, SimpleNamespace()),
        )

    async with db_session() as session:
        rejected = await CrawlRunRepository(session).one(run_id)
        attempt = await session.get(CrawlAttempts, attempt_id)
        assert attempt is not None
        assert rejected.phase == CrawlPhase.TERMINAL
        assert rejected.outcome == CrawlOutcome.FAILED
        assert rejected.failure_code == CrawlFailureCode.INVALID_DISPATCH.value
        assert attempt.lease_owner is None
        assert attempt.finished_at is not None


async def test_worker_terminalizes_a_zero_page_crawl_as_empty(
    db_session,
    admin_user,
) -> None:
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Empty crawl",
        )
        run = await _admit(session, website=website, user=admin_user)
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        task = CrawlTask.model_validate(attempt.dispatch_payload)
        dispatch_id = attempt.dispatch_id
        run_id = cast(UUID, run.id)

    container = Container(session=providers.Object(SessionProxy()))
    container.crawler.override(providers.Object(_EmptyCrawlEngine()))

    result = await crawl_task(job_id=dispatch_id, params=task, container=container)

    assert result["status"] == CrawlOutcome.EMPTY.value
    async with db_session() as session:
        finished = await CrawlRunRepository(session).one(run_id)
        job = await session.get(Jobs, dispatch_id)
        assert job is not None
        assert finished.phase == CrawlPhase.TERMINAL
        assert finished.outcome == CrawlOutcome.EMPTY
        assert finished.pages_crawled == 0
        assert job.status == Status.COMPLETE.value


async def test_file_crawl_reobserves_linked_files_before_stale_cleanup(
    db_session,
    admin_user,
    monkeypatch,
    tmp_path: Path,
) -> None:
    page_text = "<main>Page content</main>"
    file_text = "Linked file content"
    file_path = tmp_path / "guide.pdf"
    file_path.write_bytes(b"document bytes")

    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Conditional file crawl",
            download_files=True,
        )
        website_record = await session.get(WebsitesTable, website.id)
        assert website_record is not None
        page_blob = InfoBlobs(
            text=page_text,
            title=website.url,
            url=website.url,
            size=len(page_text.encode()),
            content_hash=sha256(page_text.encode()).digest(),
            http_etag='"page-v1"',
            source_id=uuid4(),
            version_state=InfoBlobVersionState.ACTIVE.value,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            embedding_model_id=website_record.embedding_model_id,
        )
        file_blob = InfoBlobs(
            text=file_text,
            title=file_path.stem,
            url=f"{website.url}/{file_path.name}",
            size=len(file_text.encode()),
            content_hash=sha256(file_text.encode()).digest(),
            source_id=uuid4(),
            version_state=InfoBlobVersionState.ACTIVE.value,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            embedding_model_id=website_record.embedding_model_id,
        )
        session.add_all((page_blob, file_blob))
        await session.flush()
        file_blob_id = file_blob.id
        run = await _admit(session, website=website, user=admin_user)
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        task = CrawlTask.model_validate(attempt.dispatch_payload)
        dispatch_id = attempt.dispatch_id

    monkeypatch.setattr(
        crawl_tasks_module,
        "persist_batch",
        AsyncMock(return_value=(1, 0, [website.url], {})),
    )
    engine = _ConditionalFileCrawlEngine(file_path)
    container = Container(session=providers.Object(SessionProxy()))
    container.crawler.override(providers.Object(engine))
    container.text_extractor.override(
        providers.Object(SimpleNamespace(extract=Mock(return_value=file_text)))
    )

    result = await crawl_task(job_id=dispatch_id, params=task, container=container)

    assert result["status"] == CrawlOutcome.SUCCEEDED.value
    assert engine.request is not None
    assert engine.request.conditional_gets == ()
    async with db_session() as session:
        persisted_file = await session.get(InfoBlobs, file_blob_id)
        assert persisted_file is not None
        assert persisted_file.version_state == InfoBlobVersionState.ACTIVE.value


async def test_page_only_crawl_forwards_conditional_validators(
    db_session,
    admin_user,
    tmp_path: Path,
) -> None:
    page_text = "<main>Page content</main>"

    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Conditional page crawl",
        )
        website_record = await session.get(WebsitesTable, website.id)
        assert website_record is not None
        session.add(
            InfoBlobs(
                text=page_text,
                title=website.url,
                url=website.url,
                size=len(page_text.encode()),
                content_hash=sha256(page_text.encode()).digest(),
                http_etag='"page-v1"',
                source_id=uuid4(),
                version_state=InfoBlobVersionState.ACTIVE.value,
                user_id=admin_user.id,
                tenant_id=admin_user.tenant_id,
                website_id=website.id,
                embedding_model_id=website_record.embedding_model_id,
            )
        )
        run = await _admit(session, website=website, user=admin_user)
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        task = CrawlTask.model_validate(attempt.dispatch_payload)
        dispatch_id = attempt.dispatch_id

    engine = _ConditionalFileCrawlEngine(tmp_path / "unused.pdf")
    container = Container(session=providers.Object(SessionProxy()))
    container.crawler.override(providers.Object(engine))

    result = await crawl_task(job_id=dispatch_id, params=task, container=container)

    assert result["status"] == CrawlOutcome.UNCHANGED.value
    assert engine.request is not None
    assert engine.request.conditional_gets == (
        ConditionalGet(url=website.url, etag='"page-v1"'),
    )


async def test_validator_database_failure_finishes_partial_and_preserves_existing_content(
    db_session,
    admin_user,
) -> None:
    content = "Published municipal guidance"
    async with db_session() as session:
        engine = session.bind
        assert engine is not None
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Validator database failure",
        )
        record = await session.get(WebsitesTable, website.id)
        assert record is not None
        provider = ModelProviders(
            tenant_id=admin_user.tenant_id,
            name=f"Validator test {uuid4()}",
            provider_type="openai",
            credentials={"api_key": "test-only"},
            config={},
            is_active=True,
        )
        session.add(provider)
        await session.flush()
        model = EmbeddingModels(
            tenant_id=admin_user.tenant_id,
            provider_id=provider.id,
            name=f"validator-test-{uuid4()}",
            open_source=False,
            family="openai",
            stability="stable",
            hosting="eu",
            max_input=512,
        )
        session.add(model)
        await session.flush()
        record.embedding_model_id = model.id
        blobs = [
            InfoBlobs(
                text=content,
                title=f"{website.url}/{path}",
                url=f"{website.url}/{path}",
                size=len(content.encode()),
                content_hash=sha256(content.encode()).digest(),
                http_etag='"old"',
                source_id=uuid4(),
                version_state=InfoBlobVersionState.ACTIVE.value,
                user_id=admin_user.id,
                tenant_id=admin_user.tenant_id,
                website_id=website.id,
                embedding_model_id=model.id,
            )
            for path in ("cached", "unchanged", "not-seen")
        ]
        session.add_all(blobs)
        run = await _admit(session, website=website, user=admin_user)
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        task = CrawlTask.model_validate(attempt.dispatch_payload)
        dispatch_id = attempt.dispatch_id
        run_id = cast(UUID, run.id)

    class ReobservedPages:
        async def crawl(self, request: CrawlRequest) -> AsyncIterator[CrawlEvent]:
            yield PageCrawled(
                url=f"{request.url}/cached",
                title="Guidance",
                content=content,
                etag='"new"',
                last_modified=None,
            )
            yield PageUnchanged(url=f"{request.url}/unchanged")
            yield CrawlFinished(
                status="completed", pages_crawled=1, pages_failed=0, pages_unchanged=1
            )

    failed_updates = 0

    def fail_after_update(
        connection, cursor, statement, parameters, context, executemany
    ):
        nonlocal failed_updates
        if statement.startswith("UPDATE info_blobs SET http_etag"):
            failed_updates += 1
            connection.exec_driver_sql("SELECT 1 / 0")

    container = Container(session=providers.Object(SessionProxy()))
    container.crawler.override(providers.Object(ReobservedPages()))
    embeddings = Mock(
        get_embeddings=AsyncMock(side_effect=AssertionError("No changed text"))
    )
    container.create_embeddings_service.override(providers.Object(embeddings))
    sa.event.listen(engine.sync_engine, "after_cursor_execute", fail_after_update)
    try:
        result = await crawl_task(job_id=dispatch_id, params=task, container=container)
    finally:
        sa.event.remove(engine.sync_engine, "after_cursor_execute", fail_after_update)

    assert failed_updates == 1
    assert result["status"] == CrawlOutcome.PARTIAL.value
    embeddings.get_embeddings.assert_not_awaited()
    async with db_session() as session:
        finished = await CrawlRunRepository(session).one(run_id)
        assert finished.phase == CrawlPhase.TERMINAL
        assert finished.outcome == CrawlOutcome.PARTIAL
        assert finished.pages_failed == 1
        stored = (
            await session.scalars(
                sa.select(InfoBlobs).where(InfoBlobs.website_id == website.id)
            )
        ).all()
        assert (
            len(stored) == 3
        )  # Includes the unvisited page: partial crawls must not prune it.
        assert all(blob.http_etag == '"old"' for blob in stored)
        assert all(
            blob.version_state == InfoBlobVersionState.ACTIVE.value for blob in stored
        )


async def test_truncated_page_validators_preserve_omitted_active_content(
    db_session,
    admin_user,
    tmp_path: Path,
) -> None:
    item_limit = 100
    page_text = "<main>Known municipal page</main>"

    async with db_session() as session:
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == admin_user.tenant_id)
            .values(crawler_settings={"closespider_itemcount": item_limit})
        )
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Bounded conditional crawl",
        )
        website_record = await session.get(WebsitesTable, website.id)
        assert website_record is not None
        session.add_all(
            [
                InfoBlobs(
                    text=page_text,
                    title=f"{website.url}/known-{index}",
                    url=f"{website.url}/known-{index}",
                    size=len(page_text.encode()),
                    content_hash=sha256(page_text.encode()).digest(),
                    http_etag=f'"page-{index}"',
                    source_id=uuid4(),
                    version_state=InfoBlobVersionState.ACTIVE.value,
                    user_id=admin_user.id,
                    tenant_id=admin_user.tenant_id,
                    website_id=website.id,
                    embedding_model_id=website_record.embedding_model_id,
                )
                for index in range(item_limit + 1)
            ]
        )
        run = await _admit(session, website=website, user=admin_user)
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        task = CrawlTask.model_validate(attempt.dispatch_payload)
        dispatch_id = attempt.dispatch_id

    engine = _ConditionalFileCrawlEngine(tmp_path / "unused.pdf")
    container = Container(session=providers.Object(SessionProxy()))
    container.crawler.override(providers.Object(engine))

    result = await crawl_task(job_id=dispatch_id, params=task, container=container)

    assert result["status"] == CrawlOutcome.PARTIAL.value
    assert engine.request is not None
    assert len(engine.request.conditional_gets) == item_limit
    assert engine.request.conditional_gets_truncated
    async with db_session() as session:
        active_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(InfoBlobs)
            .where(
                InfoBlobs.website_id == website.id,
                InfoBlobs.version_state == InfoBlobVersionState.ACTIVE.value,
            )
        )
    assert active_count == item_limit + 1


@pytest.mark.parametrize(
    ("engine", "expected_blob_count", "expects_sitemap_state"),
    [
        (_AuthoritativeEmptySitemapEngine(), 0, True),
        (_EmptyCrawlEngine(), 1, False),
    ],
    ids=("authoritative", "non-authoritative"),
)
async def test_only_authoritative_empty_sitemap_removes_withdrawn_content(
    db_session,
    admin_user,
    engine,
    expected_blob_count: int,
    expects_sitemap_state: bool,
) -> None:
    stale_text = "Withdrawn municipal guidance"
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Authoritative empty sitemap",
            crawl_type=CrawlType.SITEMAP,
        )
        website_record = await session.get(WebsitesTable, website.id)
        assert website_record is not None
        stale_blob = InfoBlobs(
            text=stale_text,
            title=f"{website.url}/withdrawn",
            url=f"{website.url}/withdrawn",
            size=len(stale_text.encode()),
            content_hash=sha256(stale_text.encode()).digest(),
            source_id=uuid4(),
            version_state=InfoBlobVersionState.ACTIVE.value,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            embedding_model_id=website_record.embedding_model_id,
        )
        session.add(stale_blob)
        await session.flush()
        stale_blob_id = stale_blob.id
        run = await _admit(session, website=website, user=admin_user)
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        task = CrawlTask.model_validate(attempt.dispatch_payload)
        dispatch_id = attempt.dispatch_id

    container = Container(session=providers.Object(SessionProxy()))
    container.crawler.override(providers.Object(engine))

    result = await crawl_task(job_id=dispatch_id, params=task, container=container)

    assert result["status"] == CrawlOutcome.EMPTY.value
    async with db_session() as session:
        blob_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(InfoBlobs)
            .where(InfoBlobs.id == stale_blob_id)
        )
        assert blob_count == expected_blob_count
        website_record = await session.get(WebsitesTable, website.id)
        assert website_record is not None
        assert (website_record.sitemap_state is not None) is expects_sitemap_state
        if website_record.sitemap_state is not None:
            assert website_record.sitemap_state["entry_count"] == 0
            assert (
                website_record.sitemap_state["fingerprint"] == sha256(b"").hexdigest()
            )


async def test_incomplete_sitemap_preserves_content_missing_from_observation(
    db_session,
    admin_user,
) -> None:
    stale_text = "Municipal guidance hidden by malformed sitemap content"
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Structurally incomplete sitemap",
            crawl_type=CrawlType.SITEMAP,
        )
        website_record = await session.get(WebsitesTable, website.id)
        assert website_record is not None
        stale_blob = InfoBlobs(
            text=stale_text,
            title=f"{website.url}/hidden",
            url=f"{website.url}/hidden",
            size=len(stale_text.encode()),
            content_hash=sha256(stale_text.encode()).digest(),
            source_id=uuid4(),
            version_state=InfoBlobVersionState.ACTIVE.value,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            embedding_model_id=website_record.embedding_model_id,
        )
        session.add(stale_blob)
        await session.flush()
        stale_blob_id = stale_blob.id
        run = await _admit(session, website=website, user=admin_user)
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        task = CrawlTask.model_validate(attempt.dispatch_payload)
        dispatch_id = attempt.dispatch_id

    container = Container(session=providers.Object(SessionProxy()))
    container.crawler.override(providers.Object(_StructurallyIncompleteSitemapEngine()))

    result = await crawl_task(job_id=dispatch_id, params=task, container=container)

    assert result["status"] == CrawlOutcome.PARTIAL.value
    async with db_session() as session:
        assert await session.get(InfoBlobs, stale_blob_id) is not None
        website_record = await session.get(WebsitesTable, website.id)
        assert website_record is not None
        assert website_record.sitemap_state is None


async def test_persistence_failure_is_not_counted_as_a_successful_page(
    db_session,
    admin_user,
    monkeypatch,
) -> None:
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Failed page persistence",
        )
        run = await _admit(session, website=website, user=admin_user)
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        task = CrawlTask.model_validate(attempt.dispatch_payload)
        dispatch_id = attempt.dispatch_id
        run_id = cast(UUID, run.id)

    monkeypatch.setattr(
        crawl_tasks_module,
        "persist_batch",
        AsyncMock(return_value=(0, 1, [], {"db_error": [website.url]})),
    )
    container = Container(session=providers.Object(SessionProxy()))
    container.crawler.override(providers.Object(_SinglePageCrawlEngine()))

    result = await crawl_task(job_id=dispatch_id, params=task, container=container)

    assert result["status"] == CrawlOutcome.FAILED.value
    assert result["pages_crawled"] == 0
    async with db_session() as session:
        finished = await CrawlRunRepository(session).one(run_id)
        assert finished.pages_crawled == 0
        assert finished.pages_failed == 1


@pytest.mark.parametrize(
    ("engine", "expected_failures", "expects_backoff"),
    [
        (_PageLimitedCrawlEngine(), 0, False),
        (_UsefulPartialCrawlEngine(), 0, False),
        (_FailureDominatedPartialCrawlEngine(), 4, True),
        (_FailureDominatedPageLimitedCrawlEngine(), 4, True),
    ],
    ids=(
        "local-page-limit",
        "useful-partial",
        "remote-failures",
        "page-limited-remote-failures",
    ),
)
async def test_partial_crawl_updates_persisted_failure_backoff_by_cause(
    db_session,
    admin_user,
    engine,
    expected_failures: int,
    expects_backoff: bool,
) -> None:
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label=f"Partial backoff {expected_failures}",
        )
        run = await _admit(session, website=website, user=admin_user)
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        task = CrawlTask.model_validate(attempt.dispatch_payload)
        dispatch_id = attempt.dispatch_id
        await session.execute(
            sa.update(WebsitesTable)
            .where(WebsitesTable.id == website.id)
            .values(
                consecutive_failures=3,
                next_retry_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )

    container = Container(session=providers.Object(SessionProxy()))
    container.crawler.override(providers.Object(engine))

    result = await crawl_task(job_id=dispatch_id, params=task, container=container)

    assert result["status"] == CrawlOutcome.PARTIAL.value
    async with db_session() as session:
        persisted = await session.scalar(
            sa.select(WebsitesTable).where(WebsitesTable.id == website.id)
        )
        assert persisted is not None
        assert persisted.consecutive_failures == expected_failures
        assert (persisted.next_retry_at is not None) is expects_backoff
        assert (persisted.last_crawled_at is not None) is (not expects_backoff)


async def test_published_files_are_not_reduced_by_unrelated_download_failures(
    db_session,
    admin_user,
    monkeypatch,
    tmp_path: Path,
) -> None:
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Partially successful file crawl",
        )
        run = await _admit(session, website=website, user=admin_user)
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        task = CrawlTask.model_validate(attempt.dispatch_payload)
        dispatch_id = attempt.dispatch_id
        run_id = cast(UUID, run.id)
        await session.execute(
            sa.update(WebsitesTable)
            .where(WebsitesTable.id == website.id)
            .values(
                consecutive_failures=3,
                next_retry_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )

    first_path = tmp_path / "first.pdf"
    second_path = tmp_path / "second.pdf"
    persist_file = AsyncMock(
        side_effect=[
            (1, 0, [first_path.stem], {}),
            (1, 0, [second_path.stem], {}),
        ]
    )
    monkeypatch.setattr(crawl_tasks_module, "persist_batch", persist_file)
    container = Container(session=providers.Object(SessionProxy()))
    container.crawler.override(
        providers.Object(_UsefulFilePartialCrawlEngine((first_path, second_path)))
    )
    container.text_extractor.override(
        providers.Object(SimpleNamespace(extract=Mock(return_value="file text")))
    )

    result = await crawl_task(job_id=dispatch_id, params=task, container=container)

    assert result["status"] == CrawlOutcome.PARTIAL.value
    assert result["files_downloaded"] == 2
    async with db_session() as session:
        finished = await CrawlRunRepository(session).one(run_id)
        persisted = await session.scalar(
            sa.select(WebsitesTable).where(WebsitesTable.id == website.id)
        )
        assert finished.files_downloaded == 2
        assert finished.files_failed == 1
        assert persisted is not None
        assert persisted.consecutive_failures == 0
        assert persisted.next_retry_at is None
        assert persisted.last_crawled_at is not None


async def test_worker_closes_crawl_stream_when_file_processing_aborts(
    db_session,
    admin_user,
    tmp_path: Path,
) -> None:
    async with db_session() as session:
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            label="Aborted file processing",
        )
        run = await _admit(session, website=website, user=admin_user)
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        task = CrawlTask.model_validate(attempt.dispatch_payload)
        dispatch_id = attempt.dispatch_id

    downloaded_path = tmp_path / "download.pdf"
    downloaded_path.write_bytes(b"document bytes")
    engine = _CloseTrackingCrawlEngine(downloaded_path)
    container = Container(session=providers.Object(SessionProxy()))
    container.crawler.override(providers.Object(engine))
    container.text_extractor.override(
        providers.Object(
            SimpleNamespace(extract=Mock(side_effect=CrawlLeaseLostError("lease lost")))
        )
    )

    with pytest.raises(CrawlLeaseLostError, match="lease lost"):
        await crawl_task(job_id=dispatch_id, params=task, container=container)

    assert engine.stream is not None
    assert engine.stream.closed is True


async def test_worker_audits_failure_as_the_initiating_user(
    db_session,
    admin_user,
    monkeypatch,
) -> None:
    async with db_session() as session:
        website_creator = Users(
            username=f"crawl-creator-{uuid4()}",
            email=f"crawl-creator-{uuid4()}@example.com",
            state="active",
            used_tokens=0,
            tenant_id=admin_user.tenant_id,
        )
        session.add(website_creator)
        await session.flush()
        website = await _persist_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=website_creator.id,
            label="Blocked crawl audit",
        )
        run = await _admit(session, website=website, user=admin_user)
        attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == run.id)
        )
        assert attempt is not None
        task = CrawlTask.model_validate(attempt.dispatch_payload)
        dispatch_id = attempt.dispatch_id

    enqueue_audit = AsyncMock()
    should_log_action = audit_service_module.AuditService._should_log_action

    async def verify_audit_session(
        service: audit_service_module.AuditService,
        tenant_id: UUID,
        action: ActionType,
    ) -> bool:
        await SessionProxy().execute(sa.text("SELECT 1"))
        return await should_log_action(service, tenant_id, action)

    monkeypatch.setattr(
        audit_service_module.AuditService,
        "_should_log_action",
        verify_audit_session,
    )
    monkeypatch.setattr(audit_service_module.job_manager, "enqueue", enqueue_audit)
    container = Container(session=providers.Object(SessionProxy()))
    container.crawler.override(providers.Object(_BlockedCrawlEngine()))

    result = await crawl_task(job_id=dispatch_id, params=task, container=container)

    assert result["status"] == CrawlOutcome.FAILED.value
    enqueue_audit.assert_awaited_once()
    audit_task, _, audit_params = enqueue_audit.await_args.args
    assert audit_task == Task.LOG_AUDIT_EVENT
    assert audit_params["actor_id"] == str(admin_user.id)
    assert audit_params["outcome"] == Outcome.FAILURE.value
    assert audit_params["error_message"] == "The website blocked the crawler"


async def test_dispatch_capacity_serves_another_tenant_before_one_tenant_backlog(
    db_session,
    admin_user,
) -> None:
    async with db_session() as session:
        second_tenant = Tenants(
            name=f"crawl-fairness-{uuid4()}",
            quota_limit=1_000_000,
            state="active",
        )
        session.add(second_tenant)
        await session.flush()
        second_user = Users(
            username="crawl-fairness-user",
            email=f"crawl-fairness-{uuid4()}@example.com",
            state="active",
            used_tokens=0,
            tenant_id=second_tenant.id,
        )
        session.add(second_user)
        await session.flush()
        tenant_a_websites = [
            await _persist_website(
                session,
                tenant_id=admin_user.tenant_id,
                user_id=admin_user.id,
                label=f"Tenant A backlog {index}",
            )
            for index in range(3)
        ]
        tenant_b_website = await _persist_website(
            session,
            tenant_id=second_tenant.id,
            user_id=second_user.id,
            label="Tenant B crawl",
        )
        for website in tenant_a_websites:
            await _admit(session, website=website, user=admin_user)
        await _admit(
            session,
            website=tenant_b_website,
            user=_user(second_user.id, second_tenant.id),
        )

    enqueue = AsyncMock(return_value=None)
    result = await crawl_dispatch.reconcile_crawl_work(
        enqueue=enqueue,
        concurrency_limit=2,
    )

    assert (result.claimed, result.dispatched) == (2, 2)
    dispatched_websites = {call.args[2].website_id for call in enqueue.await_args_list}
    assert tenant_b_website.id in dispatched_websites
    assert len(dispatched_websites & {website.id for website in tenant_a_websites}) == 1


async def test_next_free_dispatch_slot_prefers_a_late_tenant_over_backlog(
    db_session,
    admin_user,
) -> None:
    async with db_session() as session:
        second_tenant = Tenants(
            name=f"crawl-fairness-{uuid4()}",
            quota_limit=1_000_000,
            state="active",
        )
        session.add(second_tenant)
        await session.flush()
        second_user = Users(
            username="crawl-fairness-user",
            email=f"crawl-fairness-{uuid4()}@example.com",
            state="active",
            used_tokens=0,
            tenant_id=second_tenant.id,
        )
        session.add(second_user)
        await session.flush()
        tenant_a_websites = [
            await _persist_website(
                session,
                tenant_id=admin_user.tenant_id,
                user_id=admin_user.id,
                label=f"Tenant A backlog {index}",
            )
            for index in range(3)
        ]
        tenant_b_website = await _persist_website(
            session,
            tenant_id=second_tenant.id,
            user_id=second_user.id,
            label="Tenant B crawl",
        )
        for website in tenant_a_websites:
            await _admit(session, website=website, user=admin_user)
        second_tenant_id = second_tenant.id
        second_user_id = second_user.id

    initial_enqueue = AsyncMock(return_value=None)
    initial = await crawl_dispatch.reconcile_crawl_work(
        enqueue=initial_enqueue,
        concurrency_limit=2,
    )

    assert (initial.claimed, initial.dispatched) == (2, 2)
    assert {call.args[2].website_id for call in initial_enqueue.await_args_list} <= {
        website.id for website in tenant_a_websites
    }

    async with db_session() as session:
        await _admit(
            session,
            website=tenant_b_website,
            user=_user(second_user_id, second_tenant_id),
        )
        first_task = initial_enqueue.await_args_list[0].args[2]
        cancelled = await CrawlRunRepository(session).request_cancel(first_task.run_id)
        assert cancelled.run.outcome == CrawlOutcome.CANCELLED

    next_enqueue = AsyncMock(return_value=None)
    next_result = await crawl_dispatch.reconcile_crawl_work(
        enqueue=next_enqueue,
        concurrency_limit=2,
    )

    assert (next_result.claimed, next_result.dispatched) == (1, 1)
    assert next_enqueue.await_args.args[2].website_id == tenant_b_website.id


async def test_stale_redelivery_keeps_ambiguous_slots_reserved(
    db_session,
    admin_user,
) -> None:
    async with db_session() as session:
        second_tenant = Tenants(
            name=f"crawl-redelivery-{uuid4()}",
            quota_limit=1_000_000,
            state="active",
        )
        session.add(second_tenant)
        await session.flush()
        second_user = Users(
            username=f"crawl-redelivery-{uuid4()}",
            email=f"crawl-redelivery-{uuid4()}@example.com",
            state="active",
            used_tokens=0,
            tenant_id=second_tenant.id,
        )
        session.add(second_user)
        await session.flush()
        second_tenant_id = second_tenant.id
        second_user_id = second_user.id
        ambiguous_websites = [
            await _persist_website(
                session,
                tenant_id=admin_user.tenant_id,
                user_id=admin_user.id,
                label=f"Ambiguous delivery {index}",
            )
            for index in range(2)
        ]
        ambiguous_runs = [
            await _admit(session, website=website, user=admin_user)
            for website in ambiguous_websites
        ]

    first_enqueue = AsyncMock(return_value=None)
    first = await crawl_dispatch.reconcile_crawl_work(
        enqueue=first_enqueue,
        concurrency_limit=2,
    )
    assert (first.claimed, first.dispatched) == (2, 2)

    async with db_session() as session:
        attempts = list(
            await session.scalars(
                sa.select(CrawlAttempts).where(
                    CrawlAttempts.crawl_run_id.in_([run.id for run in ambiguous_runs])
                )
            )
        )
        assert len(attempts) == 2
        for attempt in attempts:
            assert attempt.dispatch_attempted_at is not None
            assert attempt.dispatched_at is not None
            attempt.dispatch_attempted_at -= timedelta(minutes=6)
            attempt.dispatched_at -= timedelta(minutes=6)

        fresh_website = await _persist_website(
            session,
            tenant_id=second_tenant_id,
            user_id=second_user_id,
            label="Fresh delivery",
        )
        fresh_run = await _admit(
            session,
            website=fresh_website,
            user=_user(second_user_id, second_tenant_id),
        )

    repair_enqueue = AsyncMock(return_value=None)
    repaired = await crawl_dispatch.reconcile_crawl_work(
        enqueue=repair_enqueue,
        concurrency_limit=2,
    )

    assert (repaired.claimed, repaired.dispatched) == (2, 2)
    repaired_websites = {
        call.args[2].website_id for call in repair_enqueue.await_args_list
    }
    assert repaired_websites == {website.id for website in ambiguous_websites}
    assert fresh_website.id not in repaired_websites

    async with db_session() as session:
        fresh_attempt = await session.scalar(
            sa.select(CrawlAttempts).where(CrawlAttempts.crawl_run_id == fresh_run.id)
        )
        assert fresh_attempt is not None
        assert fresh_attempt.dispatch_attempted_at is None
