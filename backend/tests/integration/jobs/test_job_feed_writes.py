"""Every job status write reaches its owner's jobs feed, once it has committed.

The web jobs list learns of a status change only from the job-event stream,
so a write that skips ``JobRepository.announce`` leaves the browser waiting
for its safety-net poll.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.job_table import Jobs
from eneo.jobs import job_events
from eneo.jobs.durable_dispatch import DISPATCH_STALE_AFTER, redispatch_stale_jobs
from eneo.jobs.job_models import JobInDb, Task
from eneo.jobs.job_repo import JobRepository
from eneo.main.models import Status
from eneo.websites.domain.crawl_run import CrawlFailureCode, CrawlOutcome, CrawlRun
from eneo.websites.domain.crawl_run_repo import CrawlRunRepository
from tests.integration.test_crawl_lifecycle import _job, _task, _website_identity

pytestmark = pytest.mark.integration


class Rolled(Exception):
    """Raised inside a transaction to roll it back."""


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[JobInDb]:
    sent: list[JobInDb] = []

    async def record(job: JobInDb, redis=None) -> None:
        sent.append(job)

    monkeypatch.setattr(job_events, "publish_job_update", record)
    return sent


async def _settle() -> None:
    # After-commit publishes run as tasks on the next loop iterations.
    for _ in range(5):
        await asyncio.sleep(0)


async def _assert_published_as_the_repository_would(
    db_session, published: list[JobInDb], job_id: UUID, user_id: UUID, status: Status
) -> None:
    await _settle()
    sent = [job for job in published if job.id == job_id]
    assert [job.status for job in sent] == [status]
    assert sent[0].user_id == user_id
    async with db_session() as session:
        stored = await JobRepository(session).get_job(job_id)
    assert stored is not None
    assert job_events.job_event_payload(sent[0]) == job_events.job_event_payload(stored)


async def _queued_attempt(db_session, admin_user, space_factory):
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
            task=_task(website=website, run_id=run.id, attempt_id=attempt_id, job=job),
        )
        await repo.mark_dispatched(attempt_id)
        return attempt_id, job.id


async def _claim(session, attempt_id: UUID, job_id: UUID) -> None:
    assert await CrawlRunRepository(session).claim_attempt(
        attempt_id,
        dispatch_id=job_id,
        lease_owner="crawler-1",
        lease_duration=timedelta(minutes=5),
    )


async def test_claimed_crawl_is_published_in_progress_after_commit_only(
    db_session, admin_user, space_factory, published
) -> None:
    attempt_id, job_id = await _queued_attempt(db_session, admin_user, space_factory)

    with pytest.raises(Rolled):
        async with db_session() as session:
            await _claim(session, attempt_id, job_id)
            raise Rolled
    await _settle()
    assert [job for job in published if job.id == job_id] == []

    async with db_session() as session:
        await _claim(session, attempt_id, job_id)
        await _settle()
        assert [job for job in published if job.id == job_id] == []

    await _assert_published_as_the_repository_would(
        db_session, published, job_id, admin_user.id, Status.IN_PROGRESS
    )


@pytest.mark.parametrize(
    ("outcome", "failure_code", "status"),
    [
        (CrawlOutcome.SUCCEEDED, None, Status.COMPLETE),
        (CrawlOutcome.FAILED, CrawlFailureCode.PROCESSING_FAILED, Status.FAILED),
    ],
)
async def test_finished_crawl_is_published_terminal_after_commit_only(
    db_session,
    admin_user,
    space_factory,
    published,
    outcome: CrawlOutcome,
    failure_code: CrawlFailureCode | None,
    status: Status,
) -> None:
    attempt_id, job_id = await _queued_attempt(db_session, admin_user, space_factory)
    async with db_session() as session:
        await _claim(session, attempt_id, job_id)
    await _settle()
    published.clear()

    async with db_session() as session:
        assert await CrawlRunRepository(session).finish_attempt(
            attempt_id,
            lease_owner="crawler-1",
            outcome=outcome,
            failure_code=failure_code,
            failure_detail=None if failure_code is None else "Crawler failed",
        )
        await _settle()
        assert published == []

    await _assert_published_as_the_repository_would(
        db_session, published, job_id, admin_user.id, status
    )


async def test_invalid_dispatch_envelope_failure_is_published_after_commit_only(
    db_session, admin_user, published
) -> None:
    job_id = uuid4()
    async with db_session() as session:
        await session.execute(
            sa.insert(Jobs).values(
                id=job_id,
                user_id=admin_user.id,
                task=Task.UPLOAD_FILE.value,
                status=Status.QUEUED.value,
                name="broken.txt",
                dispatch_envelope={"schema_version": 1, "task": "nonsense"},
                created_at=datetime.now(timezone.utc) - DISPATCH_STALE_AFTER * 2,
            )
        )

    async def enqueue(*_args):
        return None

    async with db_session() as session:
        await redispatch_stale_jobs(session, enqueue=enqueue)
        await _settle()
        assert [job for job in published if job.id == job_id] == []

    await _assert_published_as_the_repository_would(
        db_session, published, job_id, admin_user.id, Status.FAILED
    )
