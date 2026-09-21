import asyncio
import contextlib
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.database.database import AsyncSession
from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.model_providers.infrastructure.litellm_provider import (
    ResolvedLiteLLMProvider,
)
from eneo.websites.domain.crawl_run import (
    CrawlFailureCode,
    CrawlOrigin,
    CrawlOutcome,
)
from eneo.websites.domain.crawl_schedule import (
    SchedulerRunRecord,
    SchedulerTenantCounts,
)
from eneo.worker.crawl_tasks import (
    _QUEUE_CLOSED,
    _build_embedding_model_spec,
    _ByteBoundedQueue,
    _classify_crawl_outcome,
    _crawl_counts_as_scheduled_run,
    _failure_code_for_crawl,
    _should_store_sitemap_state,
    queue_website_crawls,
)


async def test_byte_bounded_queue_applies_backpressure_across_items() -> None:
    queue = _ByteBoundedQueue[str](max_items=10, max_bytes=10)
    await queue.put("first", weight=8)
    blocked_put = asyncio.create_task(queue.put("second", weight=4))
    await asyncio.sleep(0)

    assert not blocked_put.done()
    assert await queue.get() == "first"
    await blocked_put
    assert await queue.get() == "second"


async def test_byte_bounded_queue_can_close_while_full() -> None:
    queue = _ByteBoundedQueue[str](max_items=1, max_bytes=10)
    await queue.put("full", weight=4)

    await queue.close()

    assert await queue.get() == "full"
    assert await queue.get() is _QUEUE_CLOSED


@pytest.mark.parametrize(
    (
        "published_pages",
        "unchanged_pages",
        "published_files",
        "unchanged_files",
        "failed_pages",
        "failed_files",
        "partial",
        "expected",
    ),
    [
        (0, 0, 0, 0, 0, 0, False, CrawlOutcome.EMPTY),
        (0, 0, 0, 0, 1, 0, False, CrawlOutcome.FAILED),
        (0, 0, 0, 0, 0, 0, True, CrawlOutcome.FAILED),
        (0, 2, 0, 0, 0, 0, False, CrawlOutcome.UNCHANGED),
        (1, 0, 0, 0, 0, 0, False, CrawlOutcome.SUCCEEDED),
        (1, 0, 1, 0, 0, 0, False, CrawlOutcome.SUCCEEDED),
        (1, 0, 0, 0, 1, 0, False, CrawlOutcome.PARTIAL),
        (1, 0, 0, 0, 0, 0, True, CrawlOutcome.PARTIAL),
    ],
)
def test_crawl_outcomes_are_truthful(
    published_pages: int,
    unchanged_pages: int,
    published_files: int,
    unchanged_files: int,
    failed_pages: int,
    failed_files: int,
    partial: bool,
    expected: CrawlOutcome,
) -> None:
    assert (
        _classify_crawl_outcome(
            published_pages=published_pages,
            unchanged_pages=unchanged_pages,
            published_files=published_files,
            unchanged_files=unchanged_files,
            failed_pages=failed_pages,
            failed_files=failed_files,
            partial=partial,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("outcome", "useful_items", "failed_items", "expected"),
    [
        (CrawlOutcome.SUCCEEDED, 2, 0, True),
        (CrawlOutcome.UNCHANGED, 1, 0, True),
        (CrawlOutcome.EMPTY, 0, 0, True),
        (CrawlOutcome.PARTIAL, 2, 1, True),
        (CrawlOutcome.PARTIAL, 1, 1, False),
        (CrawlOutcome.PARTIAL, 1, 2, False),
        (CrawlOutcome.FAILED, 0, 1, False),
        (CrawlOutcome.CANCELLED, 0, 0, False),
        (CrawlOutcome.INTERRUPTED, 0, 0, False),
    ],
)
def test_only_healthy_results_reset_failure_backoff(
    outcome: CrawlOutcome,
    useful_items: int,
    failed_items: int,
    expected: bool,
) -> None:
    assert (
        _crawl_counts_as_scheduled_run(
            outcome,
            useful_items=useful_items,
            failed_items=failed_items,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("reasons", "termination_reason", "expected"),
    [
        ({"http_403": 1}, "completed", CrawlFailureCode.REMOTE_BLOCKED),
        ({"http_429": 1}, "completed", CrawlFailureCode.REMOTE_BLOCKED),
        ({"robots_disallowed": 1}, "completed", CrawlFailureCode.REMOTE_BLOCKED),
        ({"dns_error": 1}, "completed", CrawlFailureCode.REMOTE_UNREACHABLE),
        ({"connection_refused": 1}, "completed", CrawlFailureCode.REMOTE_UNREACHABLE),
        ({"request_timeout": 1}, "completed", CrawlFailureCode.TIMED_OUT),
        ({"parse_error": 1}, "completed", CrawlFailureCode.PROCESSING_FAILED),
    ],
)
def test_failed_crawls_expose_actionable_failure_codes(
    reasons: dict[str, int],
    termination_reason: str,
    expected: CrawlFailureCode,
) -> None:
    assert _failure_code_for_crawl(reasons, termination_reason) == expected


def test_missing_resources_are_distinct_from_an_incomplete_or_broken_crawl() -> None:
    assert (
        _failure_code_for_crawl(
            {"http_404": 2, "http_410": 1}, "completed", healthy_result=True
        ).value
        == "resources_missing"
    )
    for reasons, termination in (
        ({"http_404": 1}, "item_limit"),
        ({"http_404": 1}, "timeout"),
        ({"http_404": 1, "invalid_sitemap": 1}, "completed"),
        ({"http_404": 1, "http_500": 1}, "completed"),
        ({"http_404": 1, "tenant_quota_exceeded": 1}, "completed"),
        ({}, "completed"),
    ):
        assert (
            _failure_code_for_crawl(reasons, termination, healthy_result=True).value
            != "resources_missing"
        )
    assert (
        _failure_code_for_crawl(
            {"http_404": 20}, "completed", healthy_result=False
        ).value
        != "resources_missing"
    )


def test_sitemap_state_requires_a_failure_free_authoritative_outcome() -> None:
    common = {
        "has_new_state": True,
        "crawl_is_partial": False,
        "outcome": CrawlOutcome.SUCCEEDED,
    }

    assert _should_store_sitemap_state(**common, total_failed=0)
    assert not _should_store_sitemap_state(**common, total_failed=1)
    assert not _should_store_sitemap_state(
        **{**common, "outcome": CrawlOutcome.FAILED}, total_failed=0
    )
    assert not _should_store_sitemap_state(
        **{**common, "crawl_is_partial": True}, total_failed=0
    )


async def test_embedding_provider_resolution_is_tenant_scoped() -> None:
    tenant_id = uuid4()
    provider_id = uuid4()
    model_id = uuid4()
    session = AsyncMock(spec=AsyncSession)
    model = cast(
        EmbeddingModels,
        SimpleNamespace(
            id=model_id,
            name="municipal-embedding",
            litellm_model_name="stored/model",
            family="openai",
            max_input=8192,
            max_batch_size=32,
            dimensions=1536,
            open_source=False,
            provider_id=provider_id,
        ),
    )
    resolved = ResolvedLiteLLMProvider(
        id=provider_id,
        tenant_id=tenant_id,
        name="Tenant provider",
        provider_type="azure",
        credentials={"api_key": "encrypted"},
        config={"api_base": "https://example.invalid"},
    )
    loader = AsyncMock(return_value=resolved)

    spec = await _build_embedding_model_spec(
        session=session,
        embedding_model=model,
        tenant_id=tenant_id,
        load_provider=loader,
    )

    loader.assert_awaited_once_with(
        session=session,
        provider_id=provider_id,
        tenant_id=tenant_id,
    )
    assert spec.provider_id == provider_id
    assert spec.provider_type == "azure"
    assert spec.provider_credentials == resolved.credentials
    assert spec.provider_config == resolved.config
    assert spec.litellm_model_name == "azure/municipal-embedding"


class _FakeSession:
    """Session stand-in whose only job is to be told apart from its siblings."""

    def __init__(self, name: str) -> None:
        self.name = name

    @contextlib.asynccontextmanager
    async def begin(self):
        yield self


@dataclass
class _SchedulerHarness:
    """Fakes around queue_website_crawls: sessions, owner lookup, admission."""

    query_session: _FakeSession
    website_sessions: list[_FakeSession]
    repo_sessions: list[object]
    containers: list[Any]
    crawl: AsyncMock
    reconcile: AsyncMock
    recorder: AsyncMock
    scheduler: SimpleNamespace
    cron_container: Any


def _website(tenant_id: UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id or uuid4(),
        space_id=uuid4(),
        user_id=uuid4(),
        url="https://example.invalid/",
    )


def _scheduler_harness(
    monkeypatch: pytest.MonkeyPatch,
    websites: list[SimpleNamespace],
    *,
    crawl: AsyncMock | None = None,
    recorder: AsyncMock | None = None,
) -> _SchedulerHarness:
    import eneo.database.database as database_module
    import eneo.websites.application.crawl_dispatch as crawl_dispatch_module
    import eneo.worker.crawl_tasks as crawl_tasks_module

    query_session = _FakeSession("query")
    website_sessions = [_FakeSession(f"website-{i}") for i in range(len(websites))]
    sessions = iter([query_session, *website_sessions])

    @contextlib.asynccontextmanager
    async def _open_session():
        yield next(sessions)

    monkeypatch.setattr(
        database_module, "sessionmanager", SimpleNamespace(session=_open_session)
    )

    owners = {
        website.user_id: SimpleNamespace(id=website.user_id, tenant=object())
        for website in websites
    }
    repo_sessions: list[object] = []

    class _FakeUsersRepository:
        def __init__(self, session: object) -> None:
            repo_sessions.append(session)

        async def get_user_by_id(self, user_id: object) -> SimpleNamespace:
            return owners[cast(UUID, user_id)]

    monkeypatch.setattr(crawl_tasks_module, "UsersRepository", _FakeUsersRepository)

    crawl = crawl or AsyncMock()
    containers: list[Any] = []

    class _FakeContainer:
        def __init__(self, **providers_by_name: Any) -> None:
            self.providers_by_name = providers_by_name
            containers.append(self)

        def crawl_service(self) -> SimpleNamespace:
            return SimpleNamespace(crawl=crawl)

    monkeypatch.setattr(crawl_tasks_module, "Container", _FakeContainer)
    reconcile = AsyncMock()
    monkeypatch.setattr(crawl_dispatch_module, "reconcile_crawl_work", reconcile)
    recorder = recorder or AsyncMock()
    monkeypatch.setattr(crawl_tasks_module, "record_crawl_scheduler_run", recorder)

    scheduler = SimpleNamespace(
        website_sparse_repo=SimpleNamespace(session=None),
        get_websites_due_for_crawl=AsyncMock(return_value=list(websites)),
    )
    return _SchedulerHarness(
        query_session=query_session,
        website_sessions=website_sessions,
        repo_sessions=repo_sessions,
        containers=containers,
        crawl=crawl,
        reconcile=reconcile,
        recorder=recorder,
        scheduler=scheduler,
        cron_container=SimpleNamespace(crawl_scheduler_service=lambda: scheduler),
    )


async def test_queue_website_crawls_reads_owner_through_website_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each admission looks up the owner on its own transactional session.

    The cron session has no transaction, so anything that queries through it
    fails; the owner lookup and the crawl admission must both run on the
    per-website session.
    """
    website = _website()
    harness = _scheduler_harness(monkeypatch, [website])

    assert await queue_website_crawls(container=harness.cron_container) is True

    website_session = harness.website_sessions[0]
    assert harness.scheduler.website_sparse_repo.session is harness.query_session
    assert harness.repo_sessions == [website_session]
    assert harness.containers[0].providers_by_name["session"]() is website_session
    assert harness.containers[0].providers_by_name["user"]().id == website.user_id
    harness.crawl.assert_awaited_once_with(
        website, origin=CrawlOrigin.SCHEDULED, reconcile_after_commit=False
    )
    harness.reconcile.assert_awaited_once()


async def test_queue_website_crawls_records_per_tenant_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run marker counts due, admitted and failed websites per tenant."""
    tenant_a, tenant_b = uuid4(), uuid4()
    ok_site, broken_site = _website(tenant_a), _website(tenant_b)

    async def _admit(website: SimpleNamespace, **_: object) -> None:
        if website is broken_site:
            raise RuntimeError("owner gone")

    harness = _scheduler_harness(
        monkeypatch, [ok_site, broken_site], crawl=AsyncMock(side_effect=_admit)
    )

    assert await queue_website_crawls(container=harness.cron_container) is False

    harness.recorder.assert_awaited_once()
    record: SchedulerRunRecord = harness.recorder.await_args.args[0]
    assert (record.due, record.admitted, record.failed) == (2, 1, 1)
    assert record.ran_at.tzinfo is not None
    assert record.tenants == {
        tenant_a: SchedulerTenantCounts(due=1, admitted=1, failed=0),
        tenant_b: SchedulerTenantCounts(due=1, admitted=0, failed=1),
    }
    harness.reconcile.assert_awaited_once()


async def test_queue_website_crawls_survives_marker_write_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observability never fails the cron: a Redis error is logged and skipped."""
    harness = _scheduler_harness(
        monkeypatch, [_website()], recorder=AsyncMock(side_effect=ConnectionError)
    )

    assert await queue_website_crawls(container=harness.cron_container) is True

    harness.reconcile.assert_awaited_once()


async def test_queue_website_crawls_records_an_empty_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _scheduler_harness(monkeypatch, [])

    assert await queue_website_crawls(container=harness.cron_container) is True

    record: SchedulerRunRecord = harness.recorder.await_args.args[0]
    assert (record.due, record.admitted, record.failed) == (0, 0, 0)
    assert record.tenants == {}
