from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.sql import Select

from eneo.crawler.diagnostics_router import (
    get_crawler_diagnostics,
    probe_crawler_website,
)
from eneo.crawler.engine import CrawlEvent, CrawlFinished, PageCrawled
from eneo.websites.domain.crawl_run import CrawlType


class _ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _ProbeEngine:
    async def crawl(self, _request: object) -> AsyncIterator[CrawlEvent]:
        yield PageCrawled(
            url="https://example.se/",
            title="Exempel",
            content="content",
            etag=None,
            last_modified=None,
        )
        yield CrawlFinished(status="completed", pages_crawled=1, pages_failed=0)


def _container(*, tenant_id: UUID, session: object) -> MagicMock:
    container = MagicMock()
    tenant = SimpleNamespace(id=tenant_id, crawler_settings=None)
    container.tenant.return_value = tenant
    container.session.return_value = session
    container.user.return_value = SimpleNamespace(
        id=uuid4(), tenant_id=tenant_id, username="admin", email="admin@example.se"
    )
    audit_service = MagicMock()
    audit_service.log_async = AsyncMock()
    container.audit_service.return_value = audit_service
    return container


async def test_diagnostics_lists_only_rows_from_tenant_scoped_query() -> None:
    tenant_id = uuid4()
    website_id = uuid4()
    website = SimpleNamespace(
        id=website_id,
        name="Kommunen",
        url="https://example.se",
        crawl_type=CrawlType.CRAWL,
        http_auth_username=None,
        encrypted_auth_password=None,
    )
    session = MagicMock()

    async def scalars(statement: Select[tuple[object]]) -> _ScalarRows:
        assert tenant_id in statement.compile().params.values()
        return _ScalarRows([website])

    session.scalars = AsyncMock(side_effect=scalars)

    result = await get_crawler_diagnostics(
        _container(tenant_id=tenant_id, session=session)
    )

    assert result.engine == "python_async"
    assert result.execution == "in_process"
    assert [item.id for item in result.websites] == [website_id]
    assert result.capacity.max_http_requests_per_process > 0
    assert result.capacity.max_concurrent_crawl_jobs > 0


async def test_probe_rejects_website_missing_from_current_tenant() -> None:
    tenant_id = uuid4()
    website_id = uuid4()
    session = MagicMock()

    async def scalar(statement: Select[tuple[object]]) -> None:
        assert tenant_id in statement.compile().params.values()
        return None

    session.scalar = AsyncMock(side_effect=scalar)
    container = _container(tenant_id=tenant_id, session=session)

    with pytest.raises(HTTPException) as exc_info:
        await probe_crawler_website(website_id, container)

    assert exc_info.value.status_code == 404
    container.crawler.assert_not_called()


async def test_probe_returns_bounded_page_summary_without_content() -> None:
    tenant_id = uuid4()
    website_id = uuid4()
    website = SimpleNamespace(
        id=website_id,
        url="https://example.se/",
        crawl_type=CrawlType.CRAWL,
        http_auth_username=None,
        encrypted_auth_password=None,
    )
    session = MagicMock()
    session.scalar = AsyncMock(return_value=website)
    container = _container(tenant_id=tenant_id, session=session)
    container.crawler.return_value = _ProbeEngine()

    result = await probe_crawler_website(website_id, container)

    assert result.outcome == "reachable"
    assert result.pages_crawled == 1
    assert result.sample_title == "Exempel"
    assert "content" not in result.model_dump()
    container.audit_service.return_value.log_async.assert_awaited_once()
    audit_call = container.audit_service.return_value.log_async.await_args.kwargs
    assert audit_call["action"].value == "website_crawl_probed"
    assert audit_call["entity_id"] == website_id
