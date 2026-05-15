from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

import pytest
import redis.asyncio as aioredis

from intric.jobs.job_models import JobInDb, Task
from intric.main.models import Status
from intric.websites.domain import crawl_service as crawl_service_module
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.websites.domain.crawl_run import CrawlRun, CrawlType
from intric.websites.domain.crawl_service import CrawlService
from intric.websites.domain.crawl_terminal import (
    TerminalCommitResult,
    TerminalEvent,
)
from intric.websites.domain.website import UpdateInterval, WebsiteSparse
from intric.worker.redis.lua_scripts import LuaScripts

if TYPE_CHECKING:
    from intric.jobs.task_service import TaskService
    from intric.websites.domain.crawl_run_repo import CrawlRunRepository


class RecordingRedis(aioredis.Redis):
    def __init__(
        self,
        *,
        eval_return_values: list[int],
        event_log: list[str] | None = None,
        set_error: Exception | None = None,
    ) -> None:
        self.eval_return_values = eval_return_values
        self.event_log = event_log
        self.set_error = set_error
        self.eval_calls: list[tuple[object, int, tuple[object, ...]]] = []
        self.deleted_keys: list[object] = []
        self.set_calls: list[tuple[object, object, object | None]] = []

    async def eval(self, script: object, numkeys: int, *keys_and_args: object) -> int:
        self.eval_calls.append((script, numkeys, keys_and_args))
        if script == LuaScripts.RELEASE_SLOT and self.event_log is not None:
            self.event_log.append("slot_release")
        if self.eval_return_values:
            return self.eval_return_values.pop(0)
        return 0

    async def delete(self, *names: object) -> int:
        if self.event_log is not None:
            self.event_log.append("flag_delete")
        self.deleted_keys.extend(names)
        return len(names)

    async def set(
        self,
        name: object,
        value: object,
        ex: object | None = None,
    ) -> bool:
        if self.set_error is not None:
            raise self.set_error
        self.set_calls.append((name, value, ex))
        return True


class CrawlRunRepositoryStub:
    def __init__(self, *, event_log: list[str] | None = None) -> None:
        self.event_log = event_log
        self.terminal_events: list[TerminalEvent] = []
        self.terminal_error: Exception | None = None

    async def add(self, crawl_run: CrawlRun) -> CrawlRun:
        if crawl_run.id is None:
            crawl_run.id = uuid4()
        return crawl_run

    async def update(self, crawl_run: CrawlRun) -> CrawlRun:
        return crawl_run

    async def commit_terminal(self, event: TerminalEvent) -> TerminalCommitResult:
        if self.terminal_error is not None:
            raise self.terminal_error
        if self.event_log is not None:
            self.event_log.append("terminal_commit")
        self.terminal_events.append(event)
        return TerminalCommitResult(job_rows_updated=1, crawl_run_rows_updated=1)


class JobServiceStub:
    def __init__(self) -> None:
        self.failed_job_ids: list[UUID] = []

    async def fail_job(self, job_id: UUID, error_message: str) -> None:
        del error_message
        self.failed_job_ids.append(job_id)


class TaskServiceStub:
    def __init__(self, job_id: UUID, user_id: UUID) -> None:
        self.job_id = job_id
        self.user_id = user_id
        self.job_service = JobServiceStub()

    async def queue_crawl(
        self,
        name: str,
        run_id: UUID,
        url: str,
        download_files: bool = False,
        crawl_type: CrawlType = CrawlType.CRAWL,
        website_id: UUID | None = None,
        enqueue: bool = True,
    ) -> JobInDb:
        del name, run_id, url, download_files, crawl_type, website_id, enqueue
        return JobInDb(
            id=self.job_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            user_id=self.user_id,
            status=Status.QUEUED,
            task=Task.CRAWL,
            result_location=None,
            finished_at=None,
        )


def _make_service(
    *,
    redis_client: RecordingRedis,
    task_service: TaskServiceStub | None = None,
    repo: CrawlRunRepositoryStub | None = None,
) -> CrawlService:
    return CrawlService(
        repo=cast("CrawlRunRepository", repo or CrawlRunRepositoryStub()),
        task_service=cast(
            "TaskService",
            task_service or TaskServiceStub(job_id=uuid4(), user_id=uuid4()),
        ),
        redis_client=redis_client,
    )


def _make_website(
    *,
    user_id: UUID,
    tenant_id: UUID,
    website_id: UUID | None = None,
) -> WebsiteSparse:
    now = datetime.now(UTC)
    return WebsiteSparse(
        id=website_id or uuid4(),
        created_at=now,
        updated_at=now,
        user_id=user_id,
        tenant_id=tenant_id,
        embedding_model_id=uuid4(),
        space_id=uuid4(),
        name="Example",
        url="https://example.com",
        download_files=True,
        crawl_type=CrawlType.CRAWL,
        update_interval=UpdateInterval.NEVER,
        size=0,
        last_crawled_at=None,
    )


@pytest.mark.asyncio
async def test_release_job_resources_uses_canonical_slot_lua_and_keys() -> None:
    job_id = uuid4()
    tenant_id = uuid4()
    redis_client = RecordingRedis(eval_return_values=[0])
    service = _make_service(redis_client=redis_client)

    await service.release_job_resources(job_id=job_id, tenant_id=tenant_id)

    assert redis_client.eval_calls == [
        (
            LuaScripts.RELEASE_SLOT,
            1,
            (
                LuaScripts.slot_key(tenant_id),
                str(service.settings.tenant_worker_semaphore_ttl_seconds),
            ),
        )
    ]
    assert redis_client.deleted_keys == [LuaScripts.preacquired_slot_key(job_id)]


@pytest.mark.asyncio
async def test_crawl_enqueue_rollback_uses_canonical_slot_lua_and_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    tenant_id = uuid4()
    job_id = uuid4()
    redis_client = RecordingRedis(eval_return_values=[1, 0])
    repo = CrawlRunRepositoryStub()
    task_service = TaskServiceStub(job_id=job_id, user_id=user_id)
    service = _make_service(
        redis_client=redis_client,
        task_service=task_service,
        repo=repo,
    )
    website = _make_website(user_id=user_id, tenant_id=tenant_id)

    async def fail_enqueue(*, task: Task, job_id: UUID, params: object) -> bool:
        del task, job_id, params
        raise RuntimeError("enqueue failed")

    monkeypatch.setattr(crawl_service_module.job_manager, "enqueue", fail_enqueue)

    with pytest.raises(RuntimeError, match="enqueue failed"):
        await service.crawl(website)

    assert redis_client.eval_calls == [
        (
            LuaScripts.ACQUIRE_SLOT,
            1,
            (
                LuaScripts.slot_key(tenant_id),
                str(service.settings.tenant_worker_concurrency_limit),
                str(service.settings.tenant_worker_semaphore_ttl_seconds),
            ),
        ),
        (
            LuaScripts.RELEASE_SLOT,
            1,
            (
                LuaScripts.slot_key(tenant_id),
                str(service.settings.tenant_worker_semaphore_ttl_seconds),
            ),
        ),
    ]
    assert redis_client.deleted_keys == [LuaScripts.preacquired_slot_key(job_id)]
    assert task_service.job_service.failed_job_ids == []
    assert len(repo.terminal_events) == 1
    terminal_event = repo.terminal_events[0]
    assert terminal_event.job_id == job_id
    assert terminal_event.job_status == Status.FAILED
    assert terminal_event.outcome_code == CrawlOutcomeCode.CRAWL_DIRECT_ENQUEUE_FAILED
    assert terminal_event.result_location is not None
    assert "enqueue failed" in terminal_event.result_location
    assert len(terminal_event.result_location) <= 512


@pytest.mark.asyncio
async def test_crawl_enqueue_rollback_orders_resource_release_before_terminal_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    tenant_id = uuid4()
    job_id = uuid4()
    event_log: list[str] = []
    redis_client = RecordingRedis(eval_return_values=[1, 0], event_log=event_log)
    repo = CrawlRunRepositoryStub(event_log=event_log)
    task_service = TaskServiceStub(job_id=job_id, user_id=user_id)
    service = _make_service(
        redis_client=redis_client,
        task_service=task_service,
        repo=repo,
    )
    website = _make_website(user_id=user_id, tenant_id=tenant_id)

    async def fail_enqueue(*, task: Task, job_id: UUID, params: object) -> bool:
        del task, job_id, params
        raise RuntimeError("enqueue failed")

    monkeypatch.setattr(crawl_service_module.job_manager, "enqueue", fail_enqueue)

    with pytest.raises(RuntimeError, match="enqueue failed"):
        await service.crawl(website)

    assert event_log == ["flag_delete", "slot_release", "terminal_commit"]


@pytest.mark.asyncio
async def test_crawl_enqueue_failure_preserves_original_error_when_terminal_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    tenant_id = uuid4()
    job_id = uuid4()
    redis_client = RecordingRedis(eval_return_values=[1, 0])
    repo = CrawlRunRepositoryStub()
    repo.terminal_error = RuntimeError("session lost")
    task_service = TaskServiceStub(job_id=job_id, user_id=user_id)
    service = _make_service(
        redis_client=redis_client,
        task_service=task_service,
        repo=repo,
    )
    website = _make_website(user_id=user_id, tenant_id=tenant_id)
    warnings: list[str] = []

    def record_warning(message: str, **kwargs: object) -> None:
        del kwargs
        warnings.append(message)

    async def fail_enqueue(*, task: Task, job_id: UUID, params: object) -> bool:
        del task, job_id, params
        raise RuntimeError("enqueue failed")

    monkeypatch.setattr(crawl_service_module.job_manager, "enqueue", fail_enqueue)
    monkeypatch.setattr(crawl_service_module.logger, "warning", record_warning)

    with pytest.raises(RuntimeError, match="enqueue failed"):
        await service.crawl(website)

    assert task_service.job_service.failed_job_ids == []
    assert repo.terminal_events == []
    assert "Terminal commit after direct crawl enqueue failure failed" in warnings


@pytest.mark.asyncio
async def test_mark_slot_preacquired_failure_rolls_back_slot_and_commits_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    tenant_id = uuid4()
    job_id = uuid4()
    mark_error = RuntimeError("preacquired flag failed")
    redis_client = RecordingRedis(eval_return_values=[1, 0], set_error=mark_error)
    repo = CrawlRunRepositoryStub()
    task_service = TaskServiceStub(job_id=job_id, user_id=user_id)
    service = _make_service(
        redis_client=redis_client,
        task_service=task_service,
        repo=repo,
    )
    website = _make_website(user_id=user_id, tenant_id=tenant_id)

    async def unexpected_enqueue(*, task: Task, job_id: UUID, params: object) -> bool:
        del task, job_id, params
        raise AssertionError("enqueue should not run when pre-acquired flag fails")

    monkeypatch.setattr(crawl_service_module.job_manager, "enqueue", unexpected_enqueue)

    with pytest.raises(RuntimeError, match="preacquired flag failed"):
        await service.crawl(website)

    assert redis_client.deleted_keys == [LuaScripts.preacquired_slot_key(job_id)]
    assert redis_client.eval_calls[-1] == (
        LuaScripts.RELEASE_SLOT,
        1,
        (
            LuaScripts.slot_key(tenant_id),
            str(service.settings.tenant_worker_semaphore_ttl_seconds),
        ),
    )
    assert task_service.job_service.failed_job_ids == []
    assert len(repo.terminal_events) == 1
    assert repo.terminal_events[0].outcome_code == (
        CrawlOutcomeCode.CRAWL_DIRECT_ENQUEUE_FAILED
    )


def test_crawl_service_does_not_own_slot_lua_or_slot_key_literals() -> None:
    source_path = (
        Path(__file__).parents[3] / "src/intric/websites/domain/crawl_service.py"
    )
    source = source_path.read_text()

    forbidden_patterns = [
        re.compile(r"_acquire_slot_lua"),
        re.compile(r"_release_slot_lua"),
        re.compile(r"redis_client\.eval\(self\._.*slot_lua"),
        re.compile(r"redis\.call\("),
        re.compile(r'f"tenant:\\{[^}]+\\}:active_jobs"'),
        re.compile(r'f"job:\\{[^}]+\\}:slot_preacquired"'),
        re.compile(r"job_service\.fail_job"),
    ]

    for pattern in forbidden_patterns:
        assert pattern.search(source) is None
