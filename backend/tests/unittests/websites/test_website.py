from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.website import (
    WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
    UpdateInterval,
    Website,
)


def _website(
    *,
    update_interval: UpdateInterval,
    consecutive_failures: int,
) -> Website:
    now = datetime.now(timezone.utc)
    return Website(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        space_id=uuid4(),
        user_id=uuid4(),
        tenant_id=uuid4(),
        url="https://example.com",
        name=None,
        download_files=False,
        crawl_type=CrawlType.CRAWL,
        update_interval=update_interval,
        embedding_model=MagicMock(),
        size=0,
        latest_crawl=None,
        consecutive_failures=consecutive_failures,
    )


def test_auto_disabled_requires_never_interval_and_threshold_failures() -> None:
    below_threshold = _website(
        update_interval=UpdateInterval.NEVER,
        consecutive_failures=WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD - 1,
    )
    at_threshold = _website(
        update_interval=UpdateInterval.NEVER,
        consecutive_failures=WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
    )
    scheduled_at_threshold = _website(
        update_interval=UpdateInterval.DAILY,
        consecutive_failures=WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
    )

    assert not below_threshold.is_auto_disabled
    assert at_threshold.is_auto_disabled
    assert not scheduled_at_threshold.is_auto_disabled


def test_manual_schedule_change_resets_auto_disable_failures_at_threshold() -> None:
    website = _website(
        update_interval=UpdateInterval.NEVER,
        consecutive_failures=WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
    )

    website.update(update_interval=UpdateInterval.DAILY)

    assert website.consecutive_failures == 0
    assert website.next_retry_at is None
