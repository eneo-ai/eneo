from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from eneo.database.tables.websites_table import Websites
from eneo.websites.domain.crawl_run_repo import CrawlRunRepository
from eneo.websites.domain.website import UpdateInterval


def test_scheduled_run_resets_website_failure_backoff() -> None:
    now = datetime(2026, 9, 30, tzinfo=timezone.utc)
    website = Websites(
        id=uuid4(),
        url="https://intranet.example/docs",
        update_interval=UpdateInterval.DAILY,
        consecutive_failures=9,
        next_retry_at=now + timedelta(hours=24),
    )

    CrawlRunRepository._update_website_circuit_breaker(
        website, counts_as_scheduled_run=True, now=now
    )

    assert website.consecutive_failures == 0
    assert website.next_retry_at is None
    assert website.update_interval == UpdateInterval.DAILY


@pytest.mark.parametrize(
    ("prior_failures", "backoff_hours"),
    [(0, 1), (1, 2), (4, 16), (5, 24), (8, 24), (9, None)],
)
def test_failed_result_backs_off_and_disables_after_ten_failures(
    prior_failures: int,
    backoff_hours: int | None,
) -> None:
    now = datetime(2026, 9, 30, tzinfo=timezone.utc)
    website = Websites(
        id=uuid4(),
        url="https://intranet.example/docs",
        update_interval=UpdateInterval.DAILY,
        consecutive_failures=prior_failures,
        next_retry_at=now - timedelta(hours=1),
    )

    CrawlRunRepository._update_website_circuit_breaker(
        website, counts_as_scheduled_run=False, now=now
    )

    assert website.consecutive_failures == prior_failures + 1
    if backoff_hours is None:
        assert website.update_interval == UpdateInterval.NEVER
        assert website.next_retry_at is None
    else:
        assert website.update_interval == UpdateInterval.DAILY
        assert website.next_retry_at == now + timedelta(hours=backoff_hours)
