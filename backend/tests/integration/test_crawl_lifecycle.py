import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.job_table import Jobs
from eneo.database.tables.websites_table import CrawlAttempts
from eneo.database.tables.websites_table import CrawlRuns as CrawlRunsTable
from eneo.database.tables.websites_table import Websites as WebsitesTable
from eneo.jobs.job_models import Task
from eneo.main.models import Status
from eneo.websites.crawl_dependencies.crawl_models import CrawlTask
from eneo.websites.domain.crawl_run import (
    CrawlFailureCode,
    CrawlOrigin,
    CrawlOutcome,
    CrawlPhase,
    CrawlRun,
    CrawlType,
)
from eneo.websites.domain.crawl_run_repo import CrawlRunRepository
from eneo.websites.domain.website import UpdateInterval, WebsiteSparse
from eneo.websites.presentation.website_models import CrawlRunPublic

pytestmark = pytest.mark.integration


async def _website_identity(session, admin_user, space_factory) -> WebsiteSparse:
    embedding_model_id = await session.scalar(sa.select(EmbeddingModels.id).limit(1))
    assert embedding_model_id is not None
    space = await space_factory(session, f"Crawl lifecycle {uuid4()}")
    website = WebsitesTable(
        name="Lifecycle site",
        url="https://example.com",
        download_files=False,
        crawl_type=CrawlType.CRAWL,
        update_interval=UpdateInterval.NEVER,
        size=0,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        embedding_model_id=embedding_model_id,
        space_id=space.id,
    )
    session.add(website)
    await session.flush()
    return cast(
        WebsiteSparse,
        SimpleNamespace(id=website.id, tenant_id=website.tenant_id),
    )


async def _job(session, admin_user) -> Jobs:
    job = Jobs(
        user_id=admin_user.id,
        task=Task.CRAWL.value,
        status=Status.QUEUED.value,
        name="Lifecycle crawl",
    )
    session.add(job)
    await session.flush()
    return job


def _task(*, website: WebsiteSparse, run_id, attempt_id, job: Jobs) -> CrawlTask:
    return CrawlTask(
        schema_version=1,
        attempt_id=attempt_id,
        attempt_number=1,
        user_id=job.user_id,
        website_id=website.id,
        run_id=run_id,
        url="https://example.com",
        download_files=False,
        crawl_type=CrawlType.CRAWL,
        origin=CrawlOrigin.MANUAL,
    )


async def test_active_run_is_coalesced_and_does_not_depend_on_job_projection(
    db_session,
    admin_user,
    space_factory,
) -> None:
    async with db_session() as session:
        website = await _website_identity(session, admin_user, space_factory)
        repo = CrawlRunRepository(session)

        first, first_created = await repo.add_or_get_active(
            CrawlRun.create(website=website, origin=CrawlOrigin.MANUAL)
        )
        second, second_created = await repo.add_or_get_active(
            CrawlRun.create(website=website, origin=CrawlOrigin.MANUAL)
        )

        assert first_created is True
        assert second_created is False
        assert second.id == first.id

        job = await _job(session, admin_user)
        attempt_id = uuid4()
        await repo.add_attempt(
            run_id=first.id,
            attempt_id=attempt_id,
            dispatch_id=job.id,
            task=_task(
                website=website,
                run_id=first.id,
                attempt_id=attempt_id,
                job=job,
            ),
        )
        await session.delete(job)
        await session.flush()

        reloaded = await repo.one(first.id)
        assert reloaded.phase == CrawlPhase.PENDING_DISPATCH
        assert reloaded.status == Status.QUEUED
        assert reloaded.job_id is None


async def test_attempt_token_fences_claim_renewal_and_terminalization(
    db_session,
    admin_user,
    space_factory,
) -> None:
    async with db_session() as session:
        website = await _website_identity(session, admin_user, space_factory)
        repo = CrawlRunRepository(session)
        run, _ = await repo.add_or_get_active(CrawlRun.create(website=website))
        job = await _job(session, admin_user)
        attempt_id = uuid4()
        await repo.add_attempt(
            run_id=run.id,
            attempt_id=attempt_id,
            dispatch_id=job.id,
            task=_task(
                website=website,
                run_id=run.id,
                attempt_id=attempt_id,
                job=job,
            ),
        )

        task = _task(
            website=website,
            run_id=run.id,
            attempt_id=attempt_id,
            job=job,
        )
        forged_delivery = task.model_copy(
            update={"user_id": uuid4(), "url": "https://forged.invalid"}
        )
        assert await repo.mark_dispatched(attempt_id) is True
        with pytest.raises(
            ValueError,
            match="duration must be positive",
        ):
            await repo.claim_attempt(
                attempt_id,
                dispatch_id=job.id,
                lease_owner="crawler-1",
                lease_duration=timedelta(0),
            )
        claimed_task = await repo.claim_attempt(
            attempt_id,
            dispatch_id=job.id,
            lease_owner="crawler-1",
            lease_duration=timedelta(minutes=5),
        )
        assert claimed_task == task
        assert claimed_task != forged_delivery
        record = await session.scalar(
            sa.select(CrawlRunsTable).where(CrawlRunsTable.id == run.id)
        )
        assert record is not None
        assert CrawlRunPublic.model_validate(record).status == Status.IN_PROGRESS
        assert (
            await repo.renew_attempt_lease(
                attempt_id,
                lease_owner="different-worker",
                lease_duration=timedelta(minutes=10),
            )
            is False
        )
        assert (
            await repo.lock_attempt_lease(
                attempt_id,
                lease_owner="different-worker",
                expected_phase=CrawlPhase.RUNNING,
            )
            is False
        )
        assert (
            await repo.lock_attempt_lease(
                attempt_id,
                lease_owner="crawler-1",
                expected_phase=CrawlPhase.FINALIZING,
            )
            is False
        )
        assert (
            await repo.lock_attempt_lease(
                attempt_id,
                lease_owner="crawler-1",
                expected_phase=CrawlPhase.RUNNING,
            )
            is True
        )
        assert (
            await repo.mark_finalizing(
                attempt_id,
                lease_owner="crawler-1",
            )
            is True
        )
        assert (
            await repo.lock_attempt_lease(
                attempt_id,
                lease_owner="crawler-1",
                expected_phase=CrawlPhase.FINALIZING,
            )
            is True
        )
        assert (
            await repo.finish_attempt(
                uuid4(),
                outcome=CrawlOutcome.SUCCEEDED,
                lease_owner="crawler-1",
            )
            is False
        )
        assert (
            await repo.finish_attempt(
                attempt_id,
                outcome=CrawlOutcome.SUCCEEDED,
                lease_owner="different-worker",
            )
            is False
        )
        with pytest.raises(
            ValueError,
            match="Non-clean crawl outcomes require a failure code",
        ):
            await repo.finish_attempt(
                attempt_id,
                outcome=CrawlOutcome.PARTIAL,
                lease_owner="crawler-1",
            )
        assert (
            await repo.finish_attempt(
                attempt_id,
                outcome=CrawlOutcome.SUCCEEDED,
                lease_owner="crawler-1",
            )
            is True
        )
        attempt = await session.get(CrawlAttempts, attempt_id)
        assert attempt is not None
        attempt.dispatch_payload = {"schema_version": 1}
        assert (
            await repo.claim_attempt(
                attempt_id,
                dispatch_id=job.id,
                lease_owner="late-worker",
                lease_duration=timedelta(minutes=5),
            )
            is None
        )


async def test_non_clean_finish_preserves_recorded_progress_when_omitted(
    db_session,
    admin_user,
    space_factory,
) -> None:
    async with db_session() as session:
        website = await _website_identity(session, admin_user, space_factory)
        repo = CrawlRunRepository(session)
        run, _ = await repo.add_or_get_active(CrawlRun.create(website=website))
        job = await _job(session, admin_user)
        attempt_id = uuid4()
        task = _task(
            website=website,
            run_id=run.id,
            attempt_id=attempt_id,
            job=job,
        )
        await repo.add_attempt(
            run_id=run.id,
            attempt_id=attempt_id,
            dispatch_id=job.id,
            task=task,
        )
        await repo.mark_dispatched(attempt_id)
        assert (
            await repo.claim_attempt(
                attempt_id,
                dispatch_id=job.id,
                lease_owner="interrupted-worker",
                lease_duration=timedelta(minutes=5),
            )
            == task
        )
        record = await session.get(CrawlRunsTable, run.id)
        assert record is not None
        record.pages_crawled = 400
        record.files_downloaded = 3
        record.pages_failed = 2
        record.files_failed = 1
        record.failure_summary = {"request_timeout": 2}

        assert await repo.finish_attempt(
            attempt_id,
            lease_owner="interrupted-worker",
            outcome=CrawlOutcome.INTERRUPTED,
            failure_code=CrawlFailureCode.WORKER_INTERRUPTED,
            failure_detail="Worker restarted",
        )

        assert record.pages_crawled == 400
        assert record.files_downloaded == 3
        assert record.pages_failed == 2
        assert record.files_failed == 1
        assert record.failure_summary == {"request_timeout": 2}
        assert (
            await repo.finish_attempt(
                attempt_id,
                outcome=CrawlOutcome.FAILED,
                failure_code=CrawlFailureCode.PROCESSING_FAILED,
                lease_owner="crawler-1",
            )
            is False
        )

        finished = await repo.one(run.id)
        assert finished.phase == CrawlPhase.TERMINAL
        assert finished.outcome == CrawlOutcome.INTERRUPTED
        assert finished.status == Status.FAILED

        await session.delete(job)
        await session.flush()
        session.expire_all()
        history_without_job = await repo.one(run.id)
        assert history_without_job.job_id is None
        assert history_without_job.phase == CrawlPhase.TERMINAL
        assert history_without_job.outcome == CrawlOutcome.INTERRUPTED
        assert history_without_job.status == Status.FAILED

        next_run, created = await repo.add_or_get_active(
            CrawlRun.create(website=website)
        )
        assert created is True
        assert next_run.id != run.id


async def test_expired_lease_becomes_a_terminal_interruption(
    db_session,
    admin_user,
    space_factory,
) -> None:
    now = datetime.now(timezone.utc)
    async with db_session() as session:
        website = await _website_identity(session, admin_user, space_factory)
        repo = CrawlRunRepository(session)
        run, _ = await repo.add_or_get_active(CrawlRun.create(website=website))
        job = await _job(session, admin_user)
        attempt_id = uuid4()
        await repo.add_attempt(
            run_id=run.id,
            attempt_id=attempt_id,
            dispatch_id=job.id,
            task=_task(
                website=website,
                run_id=run.id,
                attempt_id=attempt_id,
                job=job,
            ),
        )
        await repo.mark_dispatched(attempt_id)
        await repo.claim_attempt(
            attempt_id,
            dispatch_id=job.id,
            lease_owner="dead-worker",
            lease_duration=timedelta(minutes=5),
        )
        await session.execute(
            sa.update(CrawlAttempts)
            .where(CrawlAttempts.id == attempt_id)
            .values(lease_expires_at=now - timedelta(seconds=1))
        )

        assert (
            await repo.renew_attempt_lease(
                attempt_id,
                lease_owner="dead-worker",
                lease_duration=timedelta(minutes=5),
            )
            is False
        )
        assert (
            await repo.finish_attempt(
                attempt_id,
                lease_owner="dead-worker",
                outcome=CrawlOutcome.SUCCEEDED,
            )
            is False
        )

        interrupted = await repo.interrupt_expired_attempts()

        assert interrupted == 1
        recovered = await repo.one(run.id)
        assert recovered.phase == CrawlPhase.TERMINAL
        assert recovered.outcome == CrawlOutcome.INTERRUPTED
        assert recovered.failure_code == CrawlFailureCode.LEASE_EXPIRED.value
        assert recovered.status == Status.FAILED


async def test_health_snapshot_reports_authoritative_phase_and_expired_lease(
    db_session,
    admin_user,
    space_factory,
) -> None:
    async with db_session() as session:
        website = await _website_identity(session, admin_user, space_factory)
        repo = CrawlRunRepository(session)
        run, _ = await repo.add_or_get_active(CrawlRun.create(website=website))

        pending = await repo.health_snapshot()
        assert pending.pending_dispatch == 1
        assert pending.active_total == 1
        assert pending.expired_leases == 0
        assert pending.oldest_active_age_seconds is not None
        assert pending.oldest_active_age_seconds >= 0

        job = await _job(session, admin_user)
        attempt_id = uuid4()
        await repo.add_attempt(
            run_id=run.id,
            attempt_id=attempt_id,
            dispatch_id=job.id,
            task=_task(
                website=website,
                run_id=run.id,
                attempt_id=attempt_id,
                job=job,
            ),
        )
        assert await repo.mark_dispatched(attempt_id) is True
        queued = await repo.health_snapshot()
        assert queued.pending_dispatch == 0
        assert queued.queued == 1
        assert queued.active_total == 1

        claimed = await repo.claim_attempt(
            attempt_id,
            dispatch_id=job.id,
            lease_owner="health-worker",
            lease_duration=timedelta(minutes=5),
        )
        assert claimed is not None
        await session.execute(
            sa.update(CrawlAttempts)
            .where(CrawlAttempts.id == attempt_id)
            .values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )

        running = await repo.health_snapshot()
        assert running.queued == 0
        assert running.running == 1
        assert running.active_total == 1
        assert running.expired_leases == 1


async def test_lease_lock_prevents_sweeper_overlap_and_stale_overwrite(
    db_session,
    admin_user,
    space_factory,
) -> None:
    async with db_session() as session:
        website = await _website_identity(session, admin_user, space_factory)
        repo = CrawlRunRepository(session)
        first_run, _ = await repo.add_or_get_active(CrawlRun.create(website=website))
        first_job = await _job(session, admin_user)
        first_attempt_id = uuid4()
        first_task = _task(
            website=website,
            run_id=first_run.id,
            attempt_id=first_attempt_id,
            job=first_job,
        )
        await repo.add_attempt(
            run_id=first_run.id,
            attempt_id=first_attempt_id,
            dispatch_id=first_job.id,
            task=first_task,
        )
        await repo.mark_dispatched(first_attempt_id)
        assert (
            await repo.claim_attempt(
                first_attempt_id,
                dispatch_id=first_job.id,
                lease_owner="first-worker",
                lease_duration=timedelta(milliseconds=500),
            )
            == first_task
        )

    lock_acquired = asyncio.Event()
    release_mutation = asyncio.Event()

    async def publish_from_first_worker() -> None:
        async with db_session() as session:
            current = await CrawlRunRepository(session).lock_attempt_lease(
                first_attempt_id,
                lease_owner="first-worker",
                expected_phase=CrawlPhase.RUNNING,
            )
            assert current is True
            lock_acquired.set()
            await release_mutation.wait()
            await session.execute(
                sa.update(WebsitesTable)
                .where(WebsitesTable.id == website.id)
                .values(sitemap_state={"writer": "first"})
            )

    publication = asyncio.create_task(publish_from_first_worker())
    await asyncio.wait_for(lock_acquired.wait(), timeout=2)
    await asyncio.sleep(0.75)

    async with db_session() as session:
        # The sweeper skips the expired attempt while its row is locked by the
        # same transaction as the publication mutation.
        assert await CrawlRunRepository(session).interrupt_expired_attempts() == 0

    release_mutation.set()
    await publication

    async with db_session() as session:
        assert await CrawlRunRepository(session).interrupt_expired_attempts() == 1

    async with db_session() as session:
        repo = CrawlRunRepository(session)
        second_run, created = await repo.add_or_get_active(
            CrawlRun.create(website=website)
        )
        assert created is True
        second_job = await _job(session, admin_user)
        second_attempt_id = uuid4()
        second_task = _task(
            website=website,
            run_id=second_run.id,
            attempt_id=second_attempt_id,
            job=second_job,
        )
        await repo.add_attempt(
            run_id=second_run.id,
            attempt_id=second_attempt_id,
            dispatch_id=second_job.id,
            task=second_task,
        )
        await repo.mark_dispatched(second_attempt_id)
        assert (
            await repo.claim_attempt(
                second_attempt_id,
                dispatch_id=second_job.id,
                lease_owner="second-worker",
                lease_duration=timedelta(minutes=5),
            )
            == second_task
        )
        assert await repo.lock_attempt_lease(
            second_attempt_id,
            lease_owner="second-worker",
            expected_phase=CrawlPhase.RUNNING,
        )
        await session.execute(
            sa.update(WebsitesTable)
            .where(WebsitesTable.id == website.id)
            .values(sitemap_state={"writer": "second"})
        )

    async with db_session() as session:
        stale_current = await CrawlRunRepository(session).lock_attempt_lease(
            first_attempt_id,
            lease_owner="first-worker",
            expected_phase=CrawlPhase.RUNNING,
        )
        if stale_current:
            await session.execute(
                sa.update(WebsitesTable)
                .where(WebsitesTable.id == website.id)
                .values(sitemap_state={"writer": "stale"})
            )
        assert stale_current is False

    async with db_session() as session:
        state = await session.scalar(
            sa.select(WebsitesTable.sitemap_state).where(WebsitesTable.id == website.id)
        )
        assert state == {"writer": "second"}
