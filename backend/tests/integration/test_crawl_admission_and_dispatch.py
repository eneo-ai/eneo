import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, call
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from eneo.audit.domain.outcome import Outcome
from eneo.crawler.engine import (
    CrawlEvent,
    CrawlFinished,
    CrawlRequest,
    PageFailed,
    PageUnchanged,
)
from eneo.database.database import AsyncSession, sessionmanager
from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.job_table import Jobs
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
) -> Website:
    embedding_model_id = await session.scalar(sa.select(EmbeddingModels.id).limit(1))
    assert embedding_model_id is not None
    record = WebsitesTable(
        name=label,
        url=f"https://{label.lower().replace(' ', '-')}.example.com",
        download_files=False,
        crawl_type=CrawlType.CRAWL,
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


async def test_expired_worker_transport_cleanup_retries_until_acknowledged(
    db_session,
    admin_user,
    monkeypatch,
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


@pytest.mark.parametrize(
    ("engine", "expected_failures", "expects_retry"),
    [
        (_PageLimitedCrawlEngine(), 0, False),
        (_FailureDominatedPartialCrawlEngine(), 4, True),
        (_FailureDominatedPageLimitedCrawlEngine(), 4, True),
    ],
    ids=("local-page-limit", "remote-failures", "page-limited-remote-failures"),
)
async def test_partial_crawl_updates_persisted_failure_backoff_by_cause(
    db_session,
    admin_user,
    engine,
    expected_failures: int,
    expects_retry: bool,
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
        assert (persisted.next_retry_at is not None) is expects_retry


async def test_worker_audits_failure_as_the_initiating_user(
    db_session,
    admin_user,
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

    audit_service = SimpleNamespace(log_async=AsyncMock())
    container = Container(session=providers.Object(SessionProxy()))
    container.crawler.override(providers.Object(_BlockedCrawlEngine()))
    container.audit_service.override(providers.Object(audit_service))

    result = await crawl_task(job_id=dispatch_id, params=task, container=container)

    assert result["status"] == CrawlOutcome.FAILED.value
    audit_service.log_async.assert_awaited_once()
    audit_call = audit_service.log_async.await_args.kwargs
    assert audit_call["user"].id == admin_user.id
    assert audit_call["outcome"] == Outcome.FAILURE
    assert audit_call["error_message"] == "The website blocked the crawler"


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
