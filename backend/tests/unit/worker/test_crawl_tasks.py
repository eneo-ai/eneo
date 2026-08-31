import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.database.database import AsyncSession
from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.model_providers.infrastructure.litellm_provider import (
    ResolvedLiteLLMProvider,
)
from eneo.websites.domain.crawl_run import CrawlFailureCode, CrawlOutcome
from eneo.worker.crawl_tasks import (
    _QUEUE_CLOSED,
    _build_embedding_model_spec,
    _ByteBoundedQueue,
    _classify_crawl_outcome,
    _crawl_counts_as_scheduled_run,
    _failure_code_for_crawl,
    _should_store_sitemap_state,
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
        (CrawlOutcome.SUCCEEDED, 1, 0, True),
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
