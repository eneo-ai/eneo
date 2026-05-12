from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from intric.crawler.crawler import Crawl, CrawlDiagnostics
from intric.crawler.parse_html import CrawledPage
from intric.websites.crawl_dependencies.crawl_models import CrawlTask
from intric.websites.domain.crawl_outcome import (
    CrawlOutcomeCode,
    CrawlTerminationReason,
)
from intric.websites.domain.crawl_run import CrawlType
from intric.worker import crawl_tasks


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
        self._execute_count = 0

    async def begin(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def execute(self, _stmt: object) -> _FakeExecuteResult:
        self._execute_count += 1
        if self._execute_count == 1:
            return _FakeWebsiteResult(self._website)
        return _FakeExecuteResult(rows=self._rows)


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

    async def execute(self, stmt: object) -> None:
        self.statements.append(stmt)


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


class _FakeJobRepo:
    async def mark_job_started(self, _job_id: UUID) -> bool:
        return True


class _FakeAuditService:
    def __init__(self):
        self.metadata: dict[str, object] | None = None

    async def log_async(self, **kwargs: object) -> None:
        metadata = kwargs.get("metadata")
        assert isinstance(metadata, dict)
        self.metadata = metadata


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
    async def session_scope() -> AsyncIterator[_FakeRecoverySession]:
        yield _FakeRecoverySession()

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
        **_kwargs: object,
    ):
        operations.append(operation_name)
        recovery_session = _FakeRecoverySession()
        recovery_sessions.append(recovery_session)
        return await operation(recovery_session)

    async def reset_tenant_retry_delay(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(crawl_tasks.Container, "session_scope", session_scope)
    monkeypatch.setattr(
        "intric.database.database.sessionmanager.create_session",
        lambda: _FakeBootstrapSession(website),
    )
    monkeypatch.setattr(
        crawl_tasks, "_get_primary_active_job_id", primary_active_job_id
    )
    monkeypatch.setattr(crawl_tasks, "execute_with_recovery", execute_with_recovery)
    monkeypatch.setattr(
        crawl_tasks, "reset_tenant_retry_delay", reset_tenant_retry_delay
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
        "terminal_crawl_run_update",
        "terminal_circuit_breaker_update",
        "terminal_fail_job",
    ]
    emitted_sql = "\n".join(
        str(stmt) for session in recovery_sessions for stmt in session.executed
    )
    assert "last_crawled_at" not in emitted_sql
    assert "last_source_verified_at" not in emitted_sql
    assert "websites.tenant_id" in emitted_sql
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
        "pages_skipped": 0,
        "pages_source_retained": 0,
        "files_downloaded": 0,
        "files_failed": 0,
        "files_skipped": 0,
        "blobs_deleted": 0,
        "successful": False,
        "outcome_code": expected_outcome_code.value,
    }
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
    async def session_scope() -> AsyncIterator[_FakeRecoverySession]:
        yield _FakeRecoverySession()

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
        **_kwargs: object,
    ):
        operations.append(operation_name)
        recovery_session = _FakeRecoverySession()
        recovery_sessions.append(recovery_session)
        return await operation(recovery_session)

    async def reset_tenant_retry_delay(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(crawl_tasks.Container, "session_scope", session_scope)
    monkeypatch.setattr(
        "intric.database.database.sessionmanager.create_session",
        lambda: _FakeBootstrapSession(
            website,
            rows=((retained_url, b"hash", embedding_model_id),),
        ),
    )
    monkeypatch.setattr(
        crawl_tasks, "_get_primary_active_job_id", primary_active_job_id
    )
    monkeypatch.setattr(crawl_tasks, "execute_with_recovery", execute_with_recovery)
    monkeypatch.setattr(
        crawl_tasks, "reset_tenant_retry_delay", reset_tenant_retry_delay
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

    @asynccontextmanager
    async def session_scope() -> AsyncIterator[_FakeRecoverySession]:
        yield _FakeRecoverySession()

    async def primary_active_job_id(
        _session: object,
        *,
        website_id: UUID,
    ) -> None:
        assert website_id == website.id
        return None

    async def execute_with_recovery(
        *,
        operation,
        **_kwargs: object,
    ):
        return await operation(_FakeRecoverySession())

    async def persist_batch(**_kwargs: object) -> PersistBatchResult:
        return PersistBatchResult(persisted_urls=(page_url,))

    async def reset_tenant_retry_delay(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(crawl_tasks.Container, "session_scope", session_scope)
    monkeypatch.setattr(
        "intric.database.database.sessionmanager.create_session",
        lambda: _FakeBootstrapSession(
            website,
            rows=((page_url, b"hash", embedding_model_id),),
        ),
    )
    monkeypatch.setattr(
        crawl_tasks, "_get_primary_active_job_id", primary_active_job_id
    )
    monkeypatch.setattr(crawl_tasks, "execute_with_recovery", execute_with_recovery)
    monkeypatch.setattr(crawl_tasks, "persist_batch", persist_batch)
    monkeypatch.setattr(
        crawl_tasks, "reset_tenant_retry_delay", reset_tenant_retry_delay
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


@pytest.mark.asyncio
async def test_record_crawl_run_outcome_code_preserves_precise_existing_outcome(
    monkeypatch: pytest.MonkeyPatch,
):
    fake_session = _FakeOutcomeSession()

    @asynccontextmanager
    async def session_scope() -> AsyncIterator[_FakeOutcomeSession]:
        yield fake_session

    monkeypatch.setattr(crawl_tasks.Container, "session_scope", session_scope)

    await crawl_tasks._record_crawl_run_outcome_code(
        run_id=uuid4(),
        outcome_code=CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR,
    )

    assert len(fake_session.statements) == 1
    assert "outcome_code IS NULL" in str(fake_session.statements[0])
