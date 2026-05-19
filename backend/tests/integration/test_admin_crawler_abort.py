from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.job_table import Jobs
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users
from intric.database.tables.websites_table import CrawlRuns, Websites
from intric.jobs.job_manager import JobManager
from intric.jobs.job_models import Task
from intric.main.models import Status
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.crawl_run_repo import CrawlRunRepository
from intric.websites.domain.crawl_terminal import TerminalCommitResult, TerminalEvent
from intric.websites.domain.website import UpdateInterval
from intric.worker.feeder.queues import CrawlPendingJobData, PendingQueue
from intric.worker.redis.lua_scripts import LuaScripts


async def _embedding_model_id(session) -> UUID:
    embedding_model_id = await session.scalar(sa.select(EmbeddingModels.id).limit(1))
    assert embedding_model_id is not None
    return embedding_model_id


async def _create_website(
    session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    embedding_model_id: UUID,
) -> Websites:
    website = Websites(
        name="Abortable queued website",
        url=f"https://abort-{uuid4()}.example.com",
        download_files=True,
        crawl_type=CrawlType.CRAWL,
        update_interval=UpdateInterval.NEVER,
        size=0,
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
    )
    session.add(website)
    await session.flush()
    return website


async def _create_crawl_job(
    session,
    *,
    user_id: UUID,
    status: Status,
) -> Jobs:
    now = datetime.now(timezone.utc)
    job = Jobs(
        id=uuid4(),
        user_id=user_id,
        task=Task.CRAWL.value,
        status=status.value,
        result_location=None,
        name="Abortable crawl job",
        finished_at=None,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    await session.flush()
    return job


async def _create_tenant_user(session) -> Users:
    tenant = Tenants(
        name=f"abort-tenant-{uuid4().hex}",
        display_name="Abort tenant isolation",
        slug=f"abort-tenant-{uuid4().hex[:20]}",
        quota_limit=1_000_000,
    )
    session.add(tenant)
    await session.flush()

    user = Users(
        email=f"abort-tenant-{uuid4().hex}@example.com",
        tenant_id=tenant.id,
        state="active",
    )
    session.add(user)
    await session.flush()
    return user


async def _create_crawl_run(
    session,
    *,
    tenant_id: UUID,
    website_id: UUID,
    job_id: UUID,
    outcome_code: CrawlOutcomeCode | None = None,
) -> CrawlRuns:
    now = datetime.now(timezone.utc)
    crawl_run = CrawlRuns(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        tenant_id=tenant_id,
        website_id=website_id,
        job_id=job_id,
        outcome_code=outcome_code.value if outcome_code is not None else None,
    )
    session.add(crawl_run)
    await session.flush()
    return crawl_run


def _install_audit_recorder(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, object]]:
    audit_calls: list[dict[str, object]] = []

    async def record_audit(
        self: AuditService,
        **kwargs: object,
    ) -> UUID | None:
        audit_calls.append(kwargs)
        return uuid4()

    monkeypatch.setattr(AuditService, "log_async", record_audit)
    return audit_calls


def _abort_audit_calls(
    audit_calls: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        audit_call
        for audit_call in audit_calls
        if audit_call.get("action") == ActionType.WEBSITE_CRAWL_ABORTED
    ]


def _assert_abort_audit_call(
    audit_calls: list[dict[str, object]],
    *,
    tenant_id: UUID,
    user_id: UUID,
    job_id: UUID,
    website_id: UUID,
    website_name: str,
    already_terminal: bool,
) -> None:
    abort_calls = _abort_audit_calls(audit_calls)
    assert len(abort_calls) == 1
    audit_call = abort_calls[0]
    assert audit_call["tenant_id"] == tenant_id
    assert audit_call["actor_id"] == user_id
    assert audit_call["action"] == ActionType.WEBSITE_CRAWL_ABORTED
    assert audit_call["entity_type"] == EntityType.WEBSITE
    assert audit_call["entity_id"] == website_id

    metadata = audit_call["metadata"]
    assert isinstance(metadata, dict)
    target = metadata["target"]
    assert isinstance(target, dict)
    assert target["id"] == str(website_id)
    assert target["name"] == website_name
    extra = metadata["extra"]
    assert isinstance(extra, dict)
    assert extra["job_id"] == str(job_id)
    assert extra["already_terminal"] == already_terminal


def _pending_job_data(
    *,
    job_id: UUID,
    user_id: UUID,
    website_id: UUID,
    run_id: UUID,
    url: str,
) -> CrawlPendingJobData:
    return {
        "job_id": str(job_id),
        "user_id": str(user_id),
        "website_id": str(website_id),
        "run_id": str(run_id),
        "url": url,
        "download_files": True,
        "crawl_type": CrawlType.CRAWL.value,
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_abort_queued_crawl_commits_terminal_abort_and_cleans_queue(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    redis_client,
    monkeypatch,
):
    aborted_job_ids: list[UUID] = []
    audit_calls = _install_audit_recorder(monkeypatch)

    async def record_abort(
        self: JobManager,
        job_id: UUID,
        *,
        timeout: float | None = None,
        poll_delay: float = 0.5,
    ) -> bool:
        aborted_job_ids.append(job_id)
        return True

    monkeypatch.setattr(JobManager, "abort_job", record_abort)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
        )
        job = await _create_crawl_job(
            session,
            user_id=admin_user.id,
            status=Status.QUEUED,
        )
        crawl_run = await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=job.id,
        )
        job_id = job.id
        crawl_run_id = crawl_run.id
        website_id = website.id
        website_url = website.url
        website.name = None
        await session.commit()

    pending_queue = PendingQueue(redis_client)
    await pending_queue.add(
        admin_user.tenant_id,
        _pending_job_data(
            job_id=job_id,
            user_id=admin_user.id,
            website_id=website_id,
            run_id=crawl_run_id,
            url=website_url,
        ),
    )
    await redis_client.set(
        LuaScripts.preacquired_slot_key(job_id), str(admin_user.tenant_id)
    )
    await redis_client.set(f"tenant:{admin_user.tenant_id}:active_jobs", 1)

    response = await client.post(
        f"/api/v1/admin/crawler/jobs/{job_id}/abort",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 204
    assert aborted_job_ids == [job_id]
    assert await redis_client.llen(f"tenant:{admin_user.tenant_id}:crawl_pending") == 0
    assert await redis_client.get(LuaScripts.preacquired_slot_key(job_id)) is None
    assert await redis_client.get(f"tenant:{admin_user.tenant_id}:active_jobs") in {
        None,
        b"0",
    }

    async with db_session() as session:
        persisted_status, persisted_finished_at = (
            await session.execute(
                sa.select(Jobs.status, Jobs.finished_at).where(Jobs.id == job_id)
            )
        ).one()
        persisted_outcome_code = await session.scalar(
            sa.select(CrawlRuns.outcome_code).where(CrawlRuns.id == crawl_run_id)
        )

    assert persisted_status == Status.FAILED.value
    assert persisted_finished_at is not None
    assert persisted_outcome_code == CrawlOutcomeCode.CRAWL_ABORTED.value
    _assert_abort_audit_call(
        audit_calls,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        job_id=job_id,
        website_id=website_id,
        website_name=website_url,
        already_terminal=False,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_abort_pending_crawl_does_not_release_unowned_tenant_slot(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    redis_client,
    monkeypatch,
):
    _install_audit_recorder(monkeypatch)

    async def record_abort(
        self: JobManager,
        job_id: UUID,
        *,
        timeout: float | None = None,
        poll_delay: float = 0.5,
    ) -> bool:
        return True

    monkeypatch.setattr(JobManager, "abort_job", record_abort)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
        )
        job = await _create_crawl_job(
            session,
            user_id=admin_user.id,
            status=Status.QUEUED,
        )
        crawl_run = await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=job.id,
        )
        job_id = job.id
        crawl_run_id = crawl_run.id
        website_id = website.id
        website_url = website.url
        await session.commit()

    pending_queue = PendingQueue(redis_client)
    await pending_queue.add(
        admin_user.tenant_id,
        _pending_job_data(
            job_id=job_id,
            user_id=admin_user.id,
            website_id=website_id,
            run_id=crawl_run_id,
            url=website_url,
        ),
    )
    await redis_client.set(f"tenant:{admin_user.tenant_id}:active_jobs", 1)

    response = await client.post(
        f"/api/v1/admin/crawler/jobs/{job_id}/abort",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 204
    assert await redis_client.llen(f"tenant:{admin_user.tenant_id}:crawl_pending") == 0
    assert await redis_client.get(f"tenant:{admin_user.tenant_id}:active_jobs") == b"1"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_abort_running_crawl_commits_terminal_and_signals_arq(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    monkeypatch,
):
    """Running aborts mark the job FAILED + outcome CRAWL_ABORTED so the
    worker's heartbeat preemption check observes the abort and exits via the
    slot-release reactor without running unsafe stale cleanup. The admin
    endpoint also signals ARQ abort with timeout=0 (signal-only, no wait)
    so the HTTP request does not block on worker unwind."""
    aborted_job_ids: list[UUID] = []
    arq_abort_timeouts: list[float | None] = []
    audit_calls = _install_audit_recorder(monkeypatch)

    async def record_abort(
        self: JobManager,
        job_id: UUID,
        *,
        timeout: float | None = None,
        poll_delay: float = 0.5,
    ) -> bool:
        aborted_job_ids.append(job_id)
        arq_abort_timeouts.append(timeout)
        return True

    monkeypatch.setattr(JobManager, "abort_job", record_abort)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
        )
        job = await _create_crawl_job(
            session,
            user_id=admin_user.id,
            status=Status.IN_PROGRESS,
        )
        crawl_run = await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=job.id,
        )
        job_id = job.id
        crawl_run_id = crawl_run.id
        website_id = website.id
        await session.commit()

    response = await client.post(
        f"/api/v1/admin/crawler/jobs/{job_id}/abort",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 204
    assert aborted_job_ids == [job_id]

    async with db_session() as session:
        persisted_status, persisted_finished_at = (
            await session.execute(
                sa.select(Jobs.status, Jobs.finished_at).where(Jobs.id == job_id)
            )
        ).one()
        persisted_outcome_code = await session.scalar(
            sa.select(CrawlRuns.outcome_code).where(CrawlRuns.id == crawl_run_id)
        )

    assert persisted_status == Status.FAILED.value
    assert persisted_finished_at is not None
    assert persisted_outcome_code == CrawlOutcomeCode.CRAWL_ABORTED.value
    assert arq_abort_timeouts == [0]
    _assert_abort_audit_call(
        audit_calls,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        job_id=job_id,
        website_id=website_id,
        website_name="Abortable queued website",
        already_terminal=False,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_abort_running_crawl_does_not_release_worker_owned_slot(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    redis_client,
    monkeypatch,
):
    """A running worker holds the tenant slot and decrements it on the way
    out via the slot-release reactor. The admin abort path must NOT decrement
    the counter or delete the preacquired flag, otherwise the worker's own
    release on exit double-decrements the counter and lets a future crawl
    exceed the configured concurrency limit."""
    _install_audit_recorder(monkeypatch)

    async def record_abort(
        self: JobManager,
        job_id: UUID,
        *,
        timeout: float | None = None,
        poll_delay: float = 0.5,
    ) -> bool:
        return True

    monkeypatch.setattr(JobManager, "abort_job", record_abort)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
        )
        job = await _create_crawl_job(
            session,
            user_id=admin_user.id,
            status=Status.IN_PROGRESS,
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=job.id,
        )
        job_id = job.id
        await session.commit()

    # Simulate a healthy running worker: the preacquired flag is still in
    # Redis (only deleted on the worker's way out by slot_release.py) and
    # the tenant counter reflects the running crawl plus one other tenant
    # crawl running on the same worker pool.
    flag_key = LuaScripts.preacquired_slot_key(job_id)
    await redis_client.set(flag_key, str(admin_user.tenant_id))
    counter_key = f"tenant:{admin_user.tenant_id}:active_jobs"
    await redis_client.set(counter_key, 2)

    response = await client.post(
        f"/api/v1/admin/crawler/jobs/{job_id}/abort",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 204
    assert await redis_client.get(counter_key) == b"2"
    assert await redis_client.get(flag_key) == str(admin_user.tenant_id).encode()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_abort_unknown_crawl_returns_not_found(
    client,
    admin_user_api_key,
    monkeypatch,
):
    audit_calls = _install_audit_recorder(monkeypatch)

    response = await client.post(
        f"/api/v1/admin/crawler/jobs/{uuid4()}/abort",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 404
    assert _abort_audit_calls(audit_calls) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_abort_orphan_queued_crawl_returns_not_found_without_arq_abort(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    monkeypatch,
):
    abort_called = False
    audit_calls = _install_audit_recorder(monkeypatch)

    async def record_abort(
        self: JobManager,
        job_id: UUID,
        *,
        timeout: float | None = None,
        poll_delay: float = 0.5,
    ) -> bool:
        nonlocal abort_called
        abort_called = True
        return True

    monkeypatch.setattr(JobManager, "abort_job", record_abort)

    async with db_session() as session:
        job = await _create_crawl_job(
            session,
            user_id=admin_user.id,
            status=Status.QUEUED,
        )
        job_id = job.id
        await session.commit()

    response = await client.post(
        f"/api/v1/admin/crawler/jobs/{job_id}/abort",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 404
    assert abort_called is False
    assert _abort_audit_calls(audit_calls) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_abort_already_aborted_crawl_is_idempotent_and_retries_cleanup(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    redis_client,
    monkeypatch,
):
    aborted_job_ids: list[UUID] = []
    audit_calls = _install_audit_recorder(monkeypatch)

    async def record_abort(
        self: JobManager,
        job_id: UUID,
        *,
        timeout: float | None = None,
        poll_delay: float = 0.5,
    ) -> bool:
        aborted_job_ids.append(job_id)
        return True

    monkeypatch.setattr(JobManager, "abort_job", record_abort)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
        )
        job = await _create_crawl_job(
            session,
            user_id=admin_user.id,
            status=Status.FAILED,
        )
        crawl_run = await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=job.id,
            outcome_code=CrawlOutcomeCode.CRAWL_ABORTED,
        )
        job_id = job.id
        crawl_run_id = crawl_run.id
        website_id = website.id
        website_url = website.url
        await session.commit()

    await PendingQueue(redis_client).add(
        admin_user.tenant_id,
        _pending_job_data(
            job_id=job_id,
            user_id=admin_user.id,
            website_id=website_id,
            run_id=crawl_run_id,
            url=website_url,
        ),
    )

    response = await client.post(
        f"/api/v1/admin/crawler/jobs/{job_id}/abort",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 204
    assert aborted_job_ids == [job_id]
    assert await redis_client.llen(f"tenant:{admin_user.tenant_id}:crawl_pending") == 0
    _assert_abort_audit_call(
        audit_calls,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        job_id=job_id,
        website_id=website_id,
        website_name="Abortable queued website",
        already_terminal=True,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_abort_other_tenant_crawl_returns_not_found_without_arq_abort(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    monkeypatch,
):
    abort_called = False
    audit_calls = _install_audit_recorder(monkeypatch)

    async def record_abort(
        self: JobManager,
        job_id: UUID,
        *,
        timeout: float | None = None,
        poll_delay: float = 0.5,
    ) -> bool:
        nonlocal abort_called
        abort_called = True
        return True

    monkeypatch.setattr(JobManager, "abort_job", record_abort)

    async with db_session() as session:
        other_user = await _create_tenant_user(session)
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=other_user.tenant_id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
        )
        job = await _create_crawl_job(
            session,
            user_id=other_user.id,
            status=Status.QUEUED,
        )
        await _create_crawl_run(
            session,
            tenant_id=other_user.tenant_id,
            website_id=website.id,
            job_id=job.id,
        )
        job_id = job.id
        await session.commit()

    response = await client.post(
        f"/api/v1/admin/crawler/jobs/{job_id}/abort",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 404
    assert abort_called is False
    assert _abort_audit_calls(audit_calls) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_abort_queued_crawl_returns_conflict_when_terminal_commit_loses_race(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    monkeypatch,
):
    abort_called = False
    audit_calls = _install_audit_recorder(monkeypatch)

    async def record_abort(
        self: JobManager,
        job_id: UUID,
        *,
        timeout: float | None = None,
        poll_delay: float = 0.5,
    ) -> bool:
        nonlocal abort_called
        abort_called = True
        return True

    async def commit_zero_rows(
        self: CrawlRunRepository,
        event: TerminalEvent,
    ) -> TerminalCommitResult:
        return TerminalCommitResult(job_rows_updated=0, crawl_run_rows_updated=0)

    monkeypatch.setattr(JobManager, "abort_job", record_abort)
    monkeypatch.setattr(CrawlRunRepository, "commit_terminal", commit_zero_rows)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
        )
        job = await _create_crawl_job(
            session,
            user_id=admin_user.id,
            status=Status.QUEUED,
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=job.id,
        )
        job_id = job.id
        await session.commit()

    response = await client.post(
        f"/api/v1/admin/crawler/jobs/{job_id}/abort",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "CRAWL_NOT_ABORTABLE"
    assert abort_called is False
    assert _abort_audit_calls(audit_calls) == []
