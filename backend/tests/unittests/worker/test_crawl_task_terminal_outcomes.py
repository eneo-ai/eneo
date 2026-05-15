from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.sql import Select

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.crawler.crawler import Crawl, CrawlDiagnostics
from intric.crawler.parse_html import CrawledPage
from intric.database.tables.info_blobs_table import InfoBlobs
from intric.database.tables.model_providers_table import ModelProviders
from intric.database.tables.websites_table import Websites
from intric.websites.crawl_dependencies.crawl_models import CrawlTask
from intric.websites.domain.crawl_outcome import (
    CrawlOutcomeCode,
    CrawlTerminationReason,
)
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.crawl_terminal import crawl_queue_enqueue_failure_message
from intric.worker import crawl_tasks
from intric.worker.crawl import CrawlSlotReleasePath, CrawlSlotReleaseResult
from intric.worker.task_manager import TaskManager


def test_terminal_zero_output_message_includes_scrapy_diagnostics() -> None:
    diagnostics = CrawlDiagnostics.from_scrapy_stats(
        {
            "downloader/request_count": 1,
            "downloader/exception_type_count/twisted.internet.error.DNSLookupError": 1,
        }
    )

    assert crawl_tasks._terminal_zero_output_message(
        CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED,
        diagnostics,
    ) == (
        "Crawl produced no pages: downloader exceptions: "
        "twisted.internet.error.DNSLookupError=1"
    )


def test_crawl_queue_enqueue_failure_message_is_bounded_and_specific() -> None:
    message = crawl_queue_enqueue_failure_message(RuntimeError("Redis unavailable"))

    assert message == "Failed to add crawl to pending queue: Redis unavailable"
    assert len(crawl_queue_enqueue_failure_message(RuntimeError("x" * 600))) == 512


@dataclass
class _FakeExecuteResult:
    rowcount: int = 1
    rows: tuple[tuple[str | None, bytes | None, UUID | None], ...] = ()

    def scalar_one_or_none(self) -> object | None:
        return None

    def tuples(self) -> list[tuple[str | None, bytes | None, UUID | None]]:
        return list(self.rows)


class _FakeBootstrapSession:
    def __init__(
        self,
        website: SimpleNamespace,
        rows: tuple[tuple[str | None, bytes | None, UUID | None], ...] = (),
    ):
        self._website = website
        self._rows = rows

    async def begin(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def execute(self, stmt: Select[tuple[object]]) -> _FakeExecuteResult:
        entity = stmt.column_descriptions[0].get("entity")
        if entity is Websites:
            return _FakeWebsiteResult(self._website)
        if entity is ModelProviders:
            return _FakeExecuteResult()
        if entity is InfoBlobs:
            return _FakeExecuteResult(rows=self._rows)
        raise AssertionError(f"Unhandled bootstrap statement entity: {entity!r}")


class _FakeWebsiteResult(_FakeExecuteResult):
    def __init__(self, website: SimpleNamespace):
        self._website = website

    def scalar_one_or_none(self) -> SimpleNamespace:
        return self._website


class _FakeRecoverySession:
    def __init__(self):
        self.executed: list[object] = []

    async def execute(self, stmt: object) -> _FakeExecuteResult:
        self.executed.append(stmt)
        return _FakeExecuteResult()

    async def scalar(self, _stmt: object) -> int:
        return 0


class _FakeOutcomeSession:
    def __init__(self):
        self.statements: list[object] = []

    async def execute(self, stmt: object) -> _FakeExecuteResult:
        self.statements.append(stmt)
        return _FakeExecuteResult()


def _compiled_params(stmt: object) -> dict[str, object]:
    compile_stmt = getattr(stmt, "compile", None)
    assert callable(compile_stmt)
    params = compile_stmt().params
    assert isinstance(params, Mapping)
    return dict(params)


class _FakeRedis:
    async def get(self, _key: str) -> None:
        return None

    async def delete(self, *_keys: str) -> int:
        return len(_keys)


class _FakeLimiter:
    async def acquire(self, _tenant_id: UUID) -> bool:
        return True

    async def release(self, _tenant_id: UUID) -> None:
        return None


async def _release_crawl_slot_after_task(
    *_args: object, **_kwargs: object
) -> CrawlSlotReleaseResult:
    return CrawlSlotReleaseResult(released=False, path=CrawlSlotReleasePath.NOOP)


class _FakeJobRepo:
    async def mark_job_started(self, _job_id: UUID) -> bool:
        return True


class _FakeAuditService:
    def __init__(self):
        self.metadata: dict[str, object] | None = None
        self.calls: list[dict[str, object]] = []

    async def log_async(self, **kwargs: object) -> None:
        metadata = kwargs.get("metadata")
        assert isinstance(metadata, dict)
        self.metadata = metadata
        self.calls.append(kwargs)


@dataclass
class _FakeCrawler:
    is_partial: bool
    termination_reason: CrawlTerminationReason
    pages: tuple[CrawledPage, ...] = ()
    source_retained_urls: frozenset[str] = frozenset()
    captured_kwargs: dict[str, object] | None = None
    diagnostics: CrawlDiagnostics = field(default_factory=CrawlDiagnostics)

    @asynccontextmanager
    async def crawl(self, **kwargs: object) -> AsyncIterator[Crawl]:
        self.captured_kwargs = kwargs
        yield Crawl(
            pages=self.pages,
            files=(),
            is_partial=self.is_partial,
            termination_reason=self.termination_reason,
            pages_count=len(self.pages),
            source_retained_urls=self.source_retained_urls,
            diagnostics=self.diagnostics,
        )


class _FakeContainer:
    def __init__(
        self,
        *,
        tenant: SimpleNamespace,
        user: SimpleNamespace,
        audit_service: _FakeAuditService,
        crawler: _FakeCrawler,
    ):
        self._tenant = tenant
        self._user = user
        self._audit_service = audit_service
        self._crawler = crawler

    def user(self) -> SimpleNamespace:
        return self._user

    def tenant(self) -> SimpleNamespace:
        return self._tenant

    def redis_client(self) -> _FakeRedis:
        return _FakeRedis()

    def tenant_concurrency_limiter(self) -> _FakeLimiter:
        return _FakeLimiter()

    def job_repo(self) -> _FakeJobRepo:
        return _FakeJobRepo()

    def crawler(self) -> _FakeCrawler:
        return self._crawler

    def text_processor(self) -> object:
        return object()

    def audit_service(self) -> _FakeAuditService:
        return self._audit_service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "crawl_type",
        "is_partial",
        "termination_reason",
        "expected_outcome_code",
        "expected_message",
        "crawler_settings",
        "expect_invalid_settings_warning",
    ),
    [
        (
            CrawlType.CRAWL,
            False,
            "completed",
            CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED,
            "Crawl produced no pages",
            {"download_timeout": True},
            True,
        ),
        (
            CrawlType.SITEMAP,
            False,
            "completed",
            CrawlOutcomeCode.CRAWL_SITEMAP_NO_PAGES,
            "Sitemap crawl produced no pages",
            {"crawl_heartbeat_interval_seconds": 60},
            False,
        ),
        (
            CrawlType.SITEMAP,
            True,
            "timeout",
            CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES,
            "Crawl timed out before collecting pages",
            {"crawl_heartbeat_interval_seconds": 60},
            False,
        ),
        (
            CrawlType.CRAWL,
            True,
            "timeout",
            CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES,
            "Crawl timed out before collecting pages",
            {"crawl_heartbeat_interval_seconds": 60},
            False,
        ),
    ],
)
async def test_terminal_no_output_records_failed_outcome_without_stale_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    crawl_type: CrawlType,
    is_partial: bool,
    termination_reason: CrawlTerminationReason,
    expected_outcome_code: CrawlOutcomeCode,
    expected_message: str,
    crawler_settings: dict[str, object],
    expect_invalid_settings_warning: bool,
):
    tenant = SimpleNamespace(
        id=uuid4(),
        slug="test",
        crawler_settings=crawler_settings,
    )
    user = SimpleNamespace(id=uuid4())
    website = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant.id,
        url="https://example.com",
        last_crawled_at=None,
        embedding_model=None,
        http_auth_username=None,
        encrypted_auth_password=None,
        user_id=user.id,
        name="Example",
        last_source_verified_at=None,
    )
    audit_service = _FakeAuditService()
    diagnostics = CrawlDiagnostics.from_scrapy_stats(
        {
            "downloader/request_count": 1,
            "downloader/exception_type_count/twisted.internet.error.DNSLookupError": 1,
        }
    )
    expected_job_message = (
        f"{expected_message}: downloader exceptions: "
        "twisted.internet.error.DNSLookupError=1"
    )
    container = _FakeContainer(
        tenant=tenant,
        user=user,
        audit_service=audit_service,
        crawler=_FakeCrawler(
            is_partial=is_partial,
            termination_reason=termination_reason,
            diagnostics=diagnostics,
        ),
    )
    operations: list[str] = []
    recovery_sessions: list[_FakeRecoverySession] = []

    @asynccontextmanager
    async def session_scope() -> AsyncIterator[_FakeBootstrapSession]:
        yield _FakeBootstrapSession(website)

    async def primary_active_job_id(
        _session: object,
        *,
        website_id: UUID,
    ) -> None:
        assert website_id == website.id
        return None

    async def execute_with_recovery(
        *,
        operation_name: str,
        operation,
    ):
        operations.append(operation_name)
        recovery_session = _FakeRecoverySession()
        recovery_sessions.append(recovery_session)
        return await operation(recovery_session)

    monkeypatch.setattr(crawl_tasks.Container, "session_scope", session_scope)
    monkeypatch.setattr(
        crawl_tasks, "_get_primary_active_job_id", primary_active_job_id
    )
    monkeypatch.setattr(crawl_tasks, "execute_with_recovery", execute_with_recovery)
    monkeypatch.setattr(
        crawl_tasks,
        "release_crawl_slot_after_task",
        _release_crawl_slot_after_task,
    )
    mock_logger = MagicMock()
    monkeypatch.setattr(crawl_tasks, "logger", mock_logger)

    result = await crawl_tasks.crawl_task(
        job_id=uuid4(),
        params=CrawlTask(
            user_id=user.id,
            website_id=website.id,
            run_id=uuid4(),
            url=website.url,
            crawl_type=crawl_type,
        ),
        container=container,
    )

    assert result == {
        "status": "failed",
        "outcome_code": expected_outcome_code.value,
    }
    assert crawl_tasks._terminal_zero_output_message(expected_outcome_code) == (
        expected_message
    )
    assert operations == [
        "terminal_zero_output_commit",
        "terminal_circuit_breaker_update",
    ]
    emitted_sql = "\n".join(
        str(stmt) for session in recovery_sessions for stmt in session.executed
    )
    assert "last_crawled_at" not in emitted_sql
    assert "last_source_verified_at" not in emitted_sql
    assert "websites.tenant_id" in emitted_sql
    terminal_crawl_run_updates = [
        _compiled_params(stmt)
        for session in recovery_sessions
        for stmt in session.executed
        if "crawl_runs" in str(stmt).lower() and "pages_crawled" in str(stmt)
    ]
    assert terminal_crawl_run_updates
    assert terminal_crawl_run_updates[0]["pages_hash_retained"] == 0
    assert terminal_crawl_run_updates[0]["files_hash_retained"] == 0
    assert terminal_crawl_run_updates[0]["files_too_large_skipped"] == 0
    terminal_job_messages = [
        _compiled_params(stmt).get("result_location")
        for session in recovery_sessions
        for stmt in session.executed
        if "jobs" in str(stmt).lower() and "result_location" in str(stmt)
    ]
    assert terminal_job_messages == [expected_job_message]
    assert audit_service.metadata is not None
    assert audit_service.metadata["crawl_stats"] == {
        "pages_crawled": 0,
        "pages_failed": 0,
        "pages_hash_retained": 0,
        "pages_source_retained": 0,
        "files_downloaded": 0,
        "files_failed": 0,
        "files_hash_retained": 0,
        "files_too_large_skipped": 0,
        "blobs_deleted": 0,
        "successful": False,
        "outcome_code": expected_outcome_code.value,
    }
    assert audit_service.calls
    audit_call = audit_service.calls[-1]
    assert audit_call["tenant_id"] == tenant.id
    assert audit_call["actor_id"] == user.id
    assert audit_call["action"] == ActionType.WEBSITE_CRAWLED
    assert audit_call["entity_type"] == EntityType.WEBSITE
    assert audit_call["entity_id"] == website.id
    assert audit_call["description"] == f"Website crawled: {website.url} - Failed"
    if expect_invalid_settings_warning:
        warning_messages = [
            str(call.args[0]) for call in mock_logger.warning.call_args_list
        ]
        assert "Invalid tenant crawler settings ignored; defaults used" in (
            warning_messages
        )


@pytest.mark.asyncio
async def test_sitemap_source_skip_cutoff_is_passed_to_crawler_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
):
    source_verified_at = datetime.fromisoformat("2026-05-12T08:00:00+00:00")
    tenant = SimpleNamespace(
        id=uuid4(),
        slug="test",
        crawler_settings={
            "crawl_sitemap_lastmod_skip_enabled": True,
            "crawl_heartbeat_interval_seconds": 60,
        },
    )
    user = SimpleNamespace(id=uuid4())
    embedding_model_id = uuid4()
    retained_url = "https://example.com/stable"
    website = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant.id,
        url="https://example.com",
        last_crawled_at=None,
        embedding_model=SimpleNamespace(
            id=embedding_model_id,
            name="text-embedding-3-small",
            litellm_model_name="openai/text-embedding-3-small",
            family=None,
            max_input=8191,
            max_batch_size=32,
            dimensions=1536,
            open_source=False,
            provider_id=None,
        ),
        http_auth_username=None,
        encrypted_auth_password=None,
        user_id=user.id,
        name="Example",
        last_source_verified_at=source_verified_at,
    )
    crawler = _FakeCrawler(
        is_partial=False,
        termination_reason="completed",
        source_retained_urls=frozenset({retained_url}),
    )
    audit_service = _FakeAuditService()
    container = _FakeContainer(
        tenant=tenant,
        user=user,
        audit_service=audit_service,
        crawler=crawler,
    )
    operations: list[str] = []
    recovery_sessions: list[_FakeRecoverySession] = []

    @asynccontextmanager
    async def session_scope() -> AsyncIterator[_FakeBootstrapSession]:
        yield _FakeBootstrapSession(
            website,
            rows=((retained_url, b"hash", embedding_model_id),),
        )

    async def primary_active_job_id(
        _session: object,
        *,
        website_id: UUID,
    ) -> None:
        assert website_id == website.id
        return None

    async def execute_with_recovery(
        *,
        operation_name: str,
        operation,
    ):
        operations.append(operation_name)
        recovery_session = _FakeRecoverySession()
        recovery_sessions.append(recovery_session)
        return await operation(recovery_session)

    monkeypatch.setattr(crawl_tasks.Container, "session_scope", session_scope)
    monkeypatch.setattr(
        crawl_tasks, "_get_primary_active_job_id", primary_active_job_id
    )
    monkeypatch.setattr(crawl_tasks, "execute_with_recovery", execute_with_recovery)
    monkeypatch.setattr(
        crawl_tasks,
        "release_crawl_slot_after_task",
        _release_crawl_slot_after_task,
    )

    result = await crawl_tasks.crawl_task(
        job_id=uuid4(),
        params=CrawlTask(
            user_id=user.id,
            website_id=website.id,
            run_id=uuid4(),
            url=website.url,
            crawl_type=CrawlType.SITEMAP,
        ),
        container=container,
    )

    assert result
    assert crawler.captured_kwargs is not None
    assert crawler.captured_kwargs["sitemap_lastmod_skip_cutoff"] == (
        source_verified_at
    )
    assert crawler.captured_kwargs["sitemap_lastmod_skip_allowed_urls"] == frozenset(
        {retained_url}
    )
    assert "website_post_crawl_timestamps_update" in operations
    emitted_sql = "\n".join(
        str(stmt) for session in recovery_sessions for stmt in session.executed
    )
    assert "last_crawled_at" in emitted_sql
    assert "last_source_verified_at" in emitted_sql
    assert audit_service.metadata is not None
    source_retention_stats = audit_service.metadata["crawl_stats"]
    assert isinstance(source_retention_stats, dict)
    assert (
        source_retention_stats["outcome_code"]
        == CrawlOutcomeCode.CRAWL_SOURCE_RETENTION_ONLY.value
    )
    assert audit_service.calls
    audit_call = audit_service.calls[-1]
    assert audit_call["tenant_id"] == tenant.id
    assert audit_call["actor_id"] == user.id
    assert audit_call["action"] == ActionType.WEBSITE_CRAWLED
    assert audit_call["entity_type"] == EntityType.WEBSITE
    assert audit_call["entity_id"] == website.id
    assert audit_call["description"] == f"Website crawled: {website.url} - Success"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("last_source_verified_at", "lastmod_skip_enabled"),
    [
        (datetime.fromisoformat("2026-05-12T08:00:00+00:00"), False),
        (None, True),
    ],
)
async def test_sitemap_source_skip_kwargs_stay_empty_when_not_allowed(
    monkeypatch: pytest.MonkeyPatch,
    last_source_verified_at: datetime | None,
    lastmod_skip_enabled: bool,
):
    from intric.worker.crawl.persistence import PersistBatchResult

    tenant = SimpleNamespace(
        id=uuid4(),
        slug="test",
        crawler_settings={
            "crawl_sitemap_lastmod_skip_enabled": lastmod_skip_enabled,
            "crawl_heartbeat_interval_seconds": 60,
        },
    )
    user = SimpleNamespace(id=uuid4())
    embedding_model_id = uuid4()
    page_url = "https://example.com/stable"
    website = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant.id,
        url="https://example.com",
        last_crawled_at=None,
        embedding_model=SimpleNamespace(
            id=embedding_model_id,
            name="text-embedding-3-small",
            litellm_model_name="openai/text-embedding-3-small",
            family=None,
            max_input=8191,
            max_batch_size=32,
            dimensions=1536,
            open_source=False,
            provider_id=None,
        ),
        http_auth_username=None,
        encrypted_auth_password=None,
        user_id=user.id,
        name="Example",
        last_source_verified_at=last_source_verified_at,
    )
    crawler = _FakeCrawler(
        is_partial=False,
        termination_reason="completed",
        pages=(CrawledPage(url=page_url, title=page_url, content="changed"),),
    )
    audit_service = _FakeAuditService()
    container = _FakeContainer(
        tenant=tenant,
        user=user,
        audit_service=audit_service,
        crawler=crawler,
    )
    original_task_manager = crawl_tasks.TaskManager
    created_task_managers: list[TaskManager] = []
    recovery_sessions: list[_FakeRecoverySession] = []

    @asynccontextmanager
    async def session_scope() -> AsyncIterator[_FakeBootstrapSession]:
        yield _FakeBootstrapSession(
            website,
            rows=((page_url, b"hash", embedding_model_id),),
        )

    async def primary_active_job_id(
        _session: object,
        *,
        website_id: UUID,
    ) -> None:
        assert website_id == website.id
        return None

    async def execute_with_recovery(
        *,
        operation_name: str,
        operation,
    ):
        assert operation_name
        recovery_session = _FakeRecoverySession()
        recovery_sessions.append(recovery_session)
        return await operation(recovery_session)

    async def persist_batch(**_kwargs: object) -> PersistBatchResult:
        return PersistBatchResult(persisted_urls=(page_url,))

    def create_task_manager(*args: object, **kwargs: object) -> TaskManager:
        task_manager = original_task_manager(*args, **kwargs)
        created_task_managers.append(task_manager)
        return task_manager

    monkeypatch.setattr(crawl_tasks.Container, "session_scope", session_scope)
    monkeypatch.setattr(
        crawl_tasks, "_get_primary_active_job_id", primary_active_job_id
    )
    monkeypatch.setattr(crawl_tasks, "execute_with_recovery", execute_with_recovery)
    monkeypatch.setattr(crawl_tasks, "TaskManager", create_task_manager)
    monkeypatch.setattr(crawl_tasks, "persist_batch", persist_batch)
    monkeypatch.setattr(
        crawl_tasks,
        "release_crawl_slot_after_task",
        _release_crawl_slot_after_task,
    )

    result = await crawl_tasks.crawl_task(
        job_id=uuid4(),
        params=CrawlTask(
            user_id=user.id,
            website_id=website.id,
            run_id=uuid4(),
            url=website.url,
            crawl_type=CrawlType.SITEMAP,
        ),
        container=container,
    )

    assert result
    assert crawler.captured_kwargs is not None
    assert crawler.captured_kwargs["sitemap_lastmod_skip_cutoff"] is None
    assert crawler.captured_kwargs["sitemap_lastmod_skip_allowed_urls"] == frozenset()
    assert audit_service.metadata is not None
    crawl_stats = audit_service.metadata["crawl_stats"]
    assert isinstance(crawl_stats, dict)
    assert crawl_stats["outcome_code"] is None
    terminal_job_locations = [
        _compiled_params(stmt).get("result_location")
        for session in recovery_sessions
        for stmt in session.executed
        if "jobs" in str(stmt).lower() and "result_location" in str(stmt)
    ]
    assert terminal_job_locations == [
        f"/api/v1/websites/{website.id}/info-blobs/",
    ]
    assert len(created_task_managers) == 1
    assert created_task_managers[0].result_location is None
    assert audit_service.calls
    audit_call = audit_service.calls[-1]
    assert audit_call["tenant_id"] == tenant.id
    assert audit_call["actor_id"] == user.id
    assert audit_call["action"] == ActionType.WEBSITE_CRAWLED
    assert audit_call["entity_type"] == EntityType.WEBSITE
    assert audit_call["entity_id"] == website.id
    assert audit_call["description"] == f"Website crawled: {website.url} - Success"


@pytest.mark.asyncio
async def test_record_crawl_task_exception_fails_job_with_detail_and_outcome(
    monkeypatch: pytest.MonkeyPatch,
):
    fake_session = _FakeOutcomeSession()

    @asynccontextmanager
    async def session_scope() -> AsyncIterator[_FakeOutcomeSession]:
        yield fake_session

    monkeypatch.setattr(crawl_tasks.Container, "session_scope", session_scope)

    await crawl_tasks._record_crawl_task_exception(
        job_id=uuid4(),
        run_id=uuid4(),
        exc=RuntimeError("crawler crashed before parsing output"),
    )

    assert len(fake_session.statements) == 2
    job_update = _compiled_params(fake_session.statements[0])
    crawl_run_update = _compiled_params(fake_session.statements[1])
    assert job_update["status"] == "failed"
    assert job_update["result_location"] == "crawler crashed before parsing output"
    assert job_update["finished_at"] is not None
    assert (
        crawl_run_update["outcome_code"] == CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR.value
    )


@pytest.mark.asyncio
async def test_record_crawl_task_exception_maps_busy_wait_max_age_to_outcome(
    monkeypatch: pytest.MonkeyPatch,
):
    fake_session = _FakeOutcomeSession()

    @asynccontextmanager
    async def session_scope() -> AsyncIterator[_FakeOutcomeSession]:
        yield fake_session

    monkeypatch.setattr(crawl_tasks.Container, "session_scope", session_scope)

    await crawl_tasks._record_crawl_task_exception(
        job_id=uuid4(),
        run_id=uuid4(),
        exc=crawl_tasks.CrawlMaxAgeExceededError(
            "Crawl job abandoned after 1801s waiting for concurrency slot"
        ),
    )

    assert len(fake_session.statements) == 2
    job_update = _compiled_params(fake_session.statements[0])
    crawl_run_update = _compiled_params(fake_session.statements[1])
    assert job_update["status"] == "failed"
    assert job_update["result_location"] == (
        "Crawl job abandoned after 1801s waiting for concurrency slot"
    )
    assert (
        crawl_run_update["outcome_code"]
        == CrawlOutcomeCode.CRAWL_MAX_AGE_EXCEEDED.value
    )
