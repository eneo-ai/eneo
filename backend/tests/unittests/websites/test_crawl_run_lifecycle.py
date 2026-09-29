from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest

from eneo.main.models import Status
from eneo.websites.domain.crawl_run import (
    CrawlOrigin,
    CrawlOutcome,
    CrawlPhase,
    CrawlRun,
)
from eneo.websites.domain.website import WebsiteSparse


def _new_run() -> CrawlRun:
    website = cast(
        WebsiteSparse,
        SimpleNamespace(id=uuid4(), tenant_id=uuid4()),
    )
    return CrawlRun.create(website=website, origin=CrawlOrigin.MANUAL)


@pytest.mark.parametrize(
    ("phase", "outcome", "expected_status"),
    [
        (CrawlPhase.PENDING_DISPATCH, None, Status.QUEUED),
        (CrawlPhase.QUEUED, None, Status.QUEUED),
        (CrawlPhase.RUNNING, None, Status.IN_PROGRESS),
        (CrawlPhase.FINALIZING, None, Status.IN_PROGRESS),
        (CrawlPhase.STOPPING, None, Status.IN_PROGRESS),
        (CrawlPhase.TERMINAL, CrawlOutcome.SUCCEEDED, Status.COMPLETE),
        (CrawlPhase.TERMINAL, CrawlOutcome.UNCHANGED, Status.COMPLETE),
        (CrawlPhase.TERMINAL, CrawlOutcome.EMPTY, Status.COMPLETE),
        (CrawlPhase.TERMINAL, CrawlOutcome.PARTIAL, Status.COMPLETE),
        (CrawlPhase.TERMINAL, CrawlOutcome.FAILED, Status.FAILED),
        (CrawlPhase.TERMINAL, CrawlOutcome.CANCELLED, Status.FAILED),
        (CrawlPhase.TERMINAL, CrawlOutcome.INTERRUPTED, Status.FAILED),
    ],
)
def test_legacy_status_is_a_projection_of_lifecycle(
    phase: CrawlPhase,
    outcome: CrawlOutcome | None,
    expected_status: Status,
) -> None:
    run = _new_run()
    run.phase = phase
    run.outcome = outcome

    assert run.status == expected_status


def test_new_run_owns_pending_lifecycle_before_dispatch() -> None:
    run = _new_run()

    assert run.id is not None
    assert run.phase == CrawlPhase.PENDING_DISPATCH
    assert run.outcome is None
    assert run.origin == CrawlOrigin.MANUAL
    assert run.attempt_count == 0
    assert run.job_id is None


def test_openapi_exposes_one_crawl_run_contract() -> None:
    from eneo.server.main import app

    crawl_run_schemas = [
        name
        for name in app.openapi()["components"]["schemas"]
        if name.endswith("CrawlRunPublic")
    ]

    assert crawl_run_schemas == ["CrawlRunPublic"]
