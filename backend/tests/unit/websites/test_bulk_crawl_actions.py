from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from eneo.main.exceptions import (
    NotFoundException,
    UnauthorizedException,
)
from eneo.websites.application.website_crud_service import (
    WebsiteBulkError,
    WebsiteBulkErrorCode,
    WebsiteCRUDService,
)
from eneo.websites.domain.crawl_run import CrawlPhase
from eneo.websites.domain.crawl_run_repo import (
    CrawlDeletionBlocker,
    WebsiteCrawlActiveError,
    WebsiteCrawlCleanupPendingError,
)


@pytest.mark.asyncio
async def test_bulk_stop_only_cancels_active_websites() -> None:
    active_website_id = uuid4()
    inactive_website_id = uuid4()
    run_id = uuid4()
    active_run = SimpleNamespace(id=run_id, phase=CrawlPhase.RUNNING)

    space_service = SimpleNamespace(
        get_space_by_website=AsyncMock(return_value=SimpleNamespace())
    )
    actor_manager = SimpleNamespace(
        get_space_actor_from_space=Mock(
            return_value=SimpleNamespace(can_create_websites=Mock(return_value=True))
        )
    )

    async def active_for_website(website_id):
        return active_run if website_id == active_website_id else None

    crawl_run_repo = SimpleNamespace(
        get_active_for_website=AsyncMock(side_effect=active_for_website)
    )
    crawl_service = SimpleNamespace(cancel=AsyncMock(return_value=active_run))
    service = WebsiteCRUDService(
        user=SimpleNamespace(),
        space_service=space_service,
        space_repo=SimpleNamespace(),
        crawl_run_repo=crawl_run_repo,
        actor_manager=actor_manager,
        crawl_service=crawl_service,
    )

    stopped, not_running, errors = await service.bulk_stop_websites(
        [active_website_id, inactive_website_id, active_website_id]
    )

    assert stopped == [active_run]
    assert not_running == [inactive_website_id]
    assert errors == []
    crawl_service.cancel.assert_awaited_once_with(run_id)


@pytest.mark.asyncio
async def test_bulk_stop_rolls_back_unexpected_failures() -> None:
    website_id = uuid4()
    service = WebsiteCRUDService(
        user=SimpleNamespace(),
        space_service=SimpleNamespace(
            get_space_by_website=AsyncMock(
                side_effect=ConnectionError("database connection lost")
            )
        ),
        space_repo=SimpleNamespace(),
        crawl_run_repo=SimpleNamespace(),
        actor_manager=SimpleNamespace(),
        crawl_service=SimpleNamespace(),
    )

    with pytest.raises(ConnectionError, match="database connection lost"):
        await service.bulk_stop_websites([website_id])


@pytest.mark.asyncio
async def test_bulk_run_reports_expected_failure_with_website_identity() -> None:
    website_id = uuid4()
    service = WebsiteCRUDService(
        user=SimpleNamespace(),
        space_service=SimpleNamespace(),
        space_repo=SimpleNamespace(),
        crawl_run_repo=SimpleNamespace(),
        actor_manager=SimpleNamespace(),
        crawl_service=SimpleNamespace(),
    )
    service.crawl_website = AsyncMock(side_effect=UnauthorizedException())

    runs, errors = await service.bulk_crawl_websites([website_id, website_id])

    assert runs == []
    assert errors == [
        WebsiteBulkError(
            website_id=website_id,
            error=WebsiteBulkErrorCode.NOT_AUTHORIZED,
        )
    ]
    service.crawl_website.assert_awaited_once_with(website_id)


@pytest.mark.asyncio
async def test_bulk_run_does_not_hide_infrastructure_failures() -> None:
    website_id = uuid4()
    service = WebsiteCRUDService(
        user=SimpleNamespace(),
        space_service=SimpleNamespace(),
        space_repo=SimpleNamespace(),
        crawl_run_repo=SimpleNamespace(),
        actor_manager=SimpleNamespace(),
        crawl_service=SimpleNamespace(),
    )
    service.crawl_website = AsyncMock(
        side_effect=ConnectionError("database connection lost")
    )

    with pytest.raises(ConnectionError, match="database connection lost"):
        await service.bulk_crawl_websites([website_id])


@pytest.mark.asyncio
async def test_delete_preserves_source_while_crawl_cleanup_is_pending() -> None:
    website_id = uuid4()
    website = SimpleNamespace(id=website_id, url="https://example.com")
    owner_space = SimpleNamespace(
        id=uuid4(),
        get_website=Mock(return_value=website),
    )
    space_service = SimpleNamespace(
        get_space_by_website=AsyncMock(return_value=owner_space)
    )
    actor_manager = SimpleNamespace(
        get_space_actor_from_space=Mock(
            return_value=SimpleNamespace(can_delete_websites=Mock(return_value=True))
        )
    )
    crawl_run_repo = SimpleNamespace(
        lock_website_deletion=AsyncMock(
            return_value=CrawlDeletionBlocker.TRANSPORT_CLEANUP
        )
    )
    crawl_service = SimpleNamespace(
        schedule_reconciliation_after_commit=Mock(),
    )
    space_repo = SimpleNamespace(hard_delete_website=AsyncMock())
    service = WebsiteCRUDService(
        user=SimpleNamespace(),
        space_service=space_service,
        space_repo=space_repo,
        crawl_run_repo=crawl_run_repo,
        actor_manager=actor_manager,
        crawl_service=crawl_service,
    )

    with pytest.raises(WebsiteCrawlCleanupPendingError):
        await service.delete_website(website_id)

    space_repo.hard_delete_website.assert_not_awaited()
    crawl_service.schedule_reconciliation_after_commit.assert_not_called()


@pytest.mark.asyncio
async def test_bulk_delete_reports_stale_sources_without_failing_the_batch() -> None:
    deleted_website_id = uuid4()
    stale_website_id = uuid4()
    deleted_website = SimpleNamespace(id=deleted_website_id)
    crawl_run_repo = SimpleNamespace(
        get_active_for_website=AsyncMock(return_value=None)
    )
    service = WebsiteCRUDService(
        user=SimpleNamespace(),
        space_service=SimpleNamespace(),
        space_repo=SimpleNamespace(),
        crawl_run_repo=crawl_run_repo,
        actor_manager=SimpleNamespace(),
        crawl_service=SimpleNamespace(),
    )

    async def authorize(website_id):
        if website_id == stale_website_id:
            raise NotFoundException()
        return deleted_website, uuid4()

    service._authorize_website_deletion = AsyncMock(side_effect=authorize)
    service._delete_authorized_website = AsyncMock()

    deleted, not_found, errors = await service.bulk_delete_websites(
        [deleted_website_id, stale_website_id, deleted_website_id]
    )

    assert deleted == [deleted_website]
    assert not_found == [stale_website_id]
    assert errors == []
    assert {
        call.args[0] for call in service._authorize_website_deletion.await_args_list
    } == {
        deleted_website_id,
        stale_website_id,
    }
    service._delete_authorized_website.assert_awaited_once()


@pytest.mark.asyncio
async def test_bulk_delete_stops_active_crawl_and_keeps_source_selected_for_retry() -> (
    None
):
    website_id = uuid4()
    run_id = uuid4()
    website = SimpleNamespace(id=website_id)
    active_run = SimpleNamespace(id=run_id)
    crawl_run_repo = SimpleNamespace(
        get_active_for_website=AsyncMock(return_value=active_run)
    )
    crawl_service = SimpleNamespace(cancel=AsyncMock(return_value=active_run))
    service = WebsiteCRUDService(
        user=SimpleNamespace(),
        space_service=SimpleNamespace(),
        space_repo=SimpleNamespace(),
        crawl_run_repo=crawl_run_repo,
        actor_manager=SimpleNamespace(),
        crawl_service=crawl_service,
    )
    service._authorize_website_deletion = AsyncMock(return_value=(website, uuid4()))
    service._delete_authorized_website = AsyncMock()

    deleted, not_found, errors = await service.bulk_delete_websites([website_id])

    assert deleted == []
    assert not_found == []
    assert errors == [
        WebsiteBulkError(
            website_id=website_id,
            error=WebsiteBulkErrorCode.CRAWL_STOP_REQUESTED,
        )
    ]
    crawl_service.cancel.assert_awaited_once_with(run_id)
    service._delete_authorized_website.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_delete_reports_an_active_crawl_admitted_during_deletion() -> None:
    website_id = uuid4()
    website = SimpleNamespace(id=website_id)
    service = WebsiteCRUDService(
        user=SimpleNamespace(),
        space_service=SimpleNamespace(),
        space_repo=SimpleNamespace(),
        crawl_run_repo=SimpleNamespace(
            get_active_for_website=AsyncMock(return_value=None)
        ),
        actor_manager=SimpleNamespace(),
        crawl_service=SimpleNamespace(),
    )
    service._authorize_website_deletion = AsyncMock(return_value=(website, uuid4()))
    service._delete_authorized_website = AsyncMock(
        side_effect=WebsiteCrawlActiveError()
    )

    deleted, not_found, errors = await service.bulk_delete_websites([website_id])

    assert deleted == []
    assert not_found == []
    assert errors == [
        WebsiteBulkError(
            website_id=website_id,
            error=WebsiteBulkErrorCode.CRAWL_ACTIVE,
        )
    ]
