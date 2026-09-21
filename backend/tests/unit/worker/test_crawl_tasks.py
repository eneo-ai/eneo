import asyncio
import contextlib
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

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


async def test_queue_website_crawls_reads_owner_through_website_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each admission looks up the owner on its own transactional session.

    The cron session has no transaction, so anything that queries through it
    fails; the owner lookup and the crawl admission must both run on the
    per-website session.
    """
    import eneo.database.database as database_module
    import eneo.websites.application.crawl_dispatch as crawl_dispatch_module
    import eneo.worker.crawl_tasks as crawl_tasks_module

    query_session = _FakeSession("query")
    website_session = _FakeSession("website")
    sessions = iter([query_session, website_session])

    @contextlib.asynccontextmanager
    async def _open_session():
        yield next(sessions)

    monkeypatch.setattr(
        database_module, "sessionmanager", SimpleNamespace(session=_open_session)
    )

    website = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        user_id=uuid4(),
        url="https://example.invalid/",
    )
    owner = SimpleNamespace(id=website.user_id, tenant=object())

    repo_sessions: list[object] = []

    class _FakeUsersRepository:
        def __init__(self, session: object) -> None:
            repo_sessions.append(session)

        async def get_user_by_id(self, user_id: object) -> SimpleNamespace:
            assert user_id == website.user_id
            return owner

    monkeypatch.setattr(crawl_tasks_module, "UsersRepository", _FakeUsersRepository)

    crawl = AsyncMock()
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

    scheduler = SimpleNamespace(
        website_sparse_repo=SimpleNamespace(session=None),
        get_websites_due_for_crawl=AsyncMock(return_value=[website]),
    )
    cron_container = SimpleNamespace(crawl_scheduler_service=lambda: scheduler)

    assert await queue_website_crawls(container=cast(Any, cron_container)) is True

    assert scheduler.website_sparse_repo.session is query_session
    assert repo_sessions == [website_session]
    assert containers[0].providers_by_name["session"]() is website_session
    assert containers[0].providers_by_name["user"]() is owner
    crawl.assert_awaited_once_with(
        website, origin=CrawlOrigin.SCHEDULED, reconcile_after_commit=False
    )
    reconcile.assert_awaited_once()
