from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from intric.crawler.crawler import Crawl
from intric.websites.crawl_dependencies.crawl_models import CrawlTask
from intric.websites.domain.crawl_outcome import (
    CrawlOutcomeCode,
    CrawlTerminationReason,
)
from intric.websites.domain.crawl_run import CrawlType
from intric.worker import crawl_tasks


@dataclass
class _FakeExecuteResult:
    rowcount: int = 1

    def scalar_one_or_none(self) -> object | None:
        return None

    def tuples(self) -> list[tuple[str | None, bytes | None, UUID | None]]:
        return []


class _FakeBootstrapSession:
    def __init__(self, website: SimpleNamespace):
        self._website = website
        self._execute_count = 0

    async def begin(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def execute(self, _stmt: object) -> _FakeExecuteResult:
        self._execute_count += 1
        if self._execute_count == 1:
            return _FakeWebsiteResult(self._website)
        return _FakeExecuteResult()


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


@dataclass(frozen=True)
class _FakeCrawler:
    is_partial: bool
    termination_reason: CrawlTerminationReason

    @asynccontextmanager
    async def crawl(self, **_kwargs: object) -> AsyncIterator[Crawl]:
        yield Crawl(
            pages=(),
            files=(),
            is_partial=self.is_partial,
            termination_reason=self.termination_reason,
            pages_count=0,
            source_retained_urls=frozenset(),
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
    container = _FakeContainer(
        tenant=tenant,
        user=user,
        audit_service=audit_service,
        crawler=_FakeCrawler(
            is_partial=is_partial,
            termination_reason=termination_reason,
        ),
    )
    operations: list[str] = []

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
        return await operation(_FakeRecoverySession())

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
