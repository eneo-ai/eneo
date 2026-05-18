"""Crawl-task duplicate-guard ownership.

The duplicate-skip logic used to live inline in `worker/crawl_tasks.py`:
a `_get_primary_active_job_id(...)` helper plus a `try`/`except Exception`
block that committed a `TerminalEvent(CRAWL_DUPLICATE_SKIPPED)` whenever
the running job was not the oldest QUEUED/IN_PROGRESS crawl for its
website. That tangled the duplicate-skip terminal commit with the
crawl-task orchestration and made ownership hard to test directly.

These tests pin the ownership split for the new
`worker/crawl/duplicate_guard.py` module:

  find_primary_active_job_id(session, *, website_id)
    Pure read of the oldest active CRAWL job for a website.

  try_duplicate_skip(*, session_scope, job_id, run_id, website_id)
    Decides whether the running job is a duplicate, commits the typed
    `TerminalEvent(CRAWL_DUPLICATE_SKIPPED)` exactly once if so, and
    returns a small `DuplicateSkipDecision` carrying the primary job ID.

Tests use behavior-focused fakes (`_FakeSession`, `_FakeCommit`) so the
duplicate-guard contract is provable without spinning up a real DB or
the full crawler stack. Integration coverage for the SQL helper remains
in `tests/integration/test_crawl_scheduler_dedupe.py`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable
from uuid import UUID, uuid4

import pytest

from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.websites.domain.crawl_terminal_source import CrawlTerminalSource
from intric.worker.crawl.duplicate_guard import (
    DuplicateSkipDecision,
    try_duplicate_skip,
)


class _FakeSession:
    """Records `commit_terminal` invocations so tests can assert exactly
    what TerminalEvent the duplicate-guard wrote. Holds no real SQL
    connection.
    """

    def __init__(self, *, primary_job_id: UUID | None) -> None:
        self.primary_job_id = primary_job_id
        self.terminal_events_committed: list[Any] = []


@asynccontextmanager
async def _session_scope_for(
    session: _FakeSession,
) -> AsyncIterator[_FakeSession]:
    yield session


def _make_session_scope(
    session: _FakeSession,
) -> Callable[[], Any]:
    def scope() -> Any:
        return _session_scope_for(session)

    return scope


@pytest.fixture(autouse=True)
def _patch_duplicate_guard_seams(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wire the duplicate-guard module's two outbound seams to the fake
    session. Both seams are functions imported at module level — patching
    via monkeypatch keeps the production caller path identical while
    letting the test substitute a predictable response.
    """
    from intric.worker.crawl import duplicate_guard

    async def fake_find(
        session: _FakeSession,
        *,
        website_id: UUID,
    ) -> UUID | None:
        del website_id  # unused — fake returns the primed value directly
        return session.primary_job_id

    async def fake_commit_terminal(session: _FakeSession, event: Any) -> Any:
        session.terminal_events_committed.append(event)

        class _Result:
            crawl_run_rows_updated = 1
            job_rows_updated = 1

        return _Result()

    monkeypatch.setattr(duplicate_guard, "find_primary_active_job_id", fake_find)
    monkeypatch.setattr(duplicate_guard, "commit_terminal", fake_commit_terminal)


@pytest.mark.asyncio
async def test_returns_none_when_no_primary_active_job_exists() -> None:
    """The first crawl for a website has no primary; duplicate-guard
    must NOT commit a terminal event and must let the caller proceed."""
    session = _FakeSession(primary_job_id=None)
    job_id = uuid4()
    run_id = uuid4()
    website_id = uuid4()

    decision = await try_duplicate_skip(
        session_scope=_make_session_scope(session),
        job_id=job_id,
        run_id=run_id,
        website_id=website_id,
    )

    assert decision is None
    assert session.terminal_events_committed == []


@pytest.mark.asyncio
async def test_returns_none_when_this_job_is_the_primary() -> None:
    """A job that IS the oldest active crawl is the canonical worker;
    duplicate-guard must NOT terminal-skip itself."""
    job_id = uuid4()
    session = _FakeSession(primary_job_id=job_id)

    decision = await try_duplicate_skip(
        session_scope=_make_session_scope(session),
        job_id=job_id,
        run_id=uuid4(),
        website_id=uuid4(),
    )

    assert decision is None
    assert session.terminal_events_committed == []


@pytest.mark.asyncio
async def test_commits_terminal_event_and_returns_decision_for_duplicate() -> None:
    """When another job is the canonical worker, duplicate-guard must
    commit ONE TerminalEvent(CRAWL_DUPLICATE_SKIPPED) and return a
    Decision carrying the primary job ID so the caller can log + return
    the duplicate skip status without re-querying the DB."""
    primary_job_id = uuid4()
    session = _FakeSession(primary_job_id=primary_job_id)
    job_id = uuid4()
    run_id = uuid4()
    website_id = uuid4()

    decision = await try_duplicate_skip(
        session_scope=_make_session_scope(session),
        job_id=job_id,
        run_id=run_id,
        website_id=website_id,
    )

    assert decision is not None
    assert isinstance(decision, DuplicateSkipDecision)
    assert decision.primary_job_id == primary_job_id

    assert len(session.terminal_events_committed) == 1
    event = session.terminal_events_committed[0]
    assert event.crawl_run_id == run_id
    assert event.job_id == job_id
    assert event.outcome_code == CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED
    assert event.terminal_source == CrawlTerminalSource.CRAWLER
    assert event.result_location is not None
    assert str(primary_job_id) in event.result_location
    # finished_at must be recent and timezone-aware so audit/event-log
    # ordering against other terminal commits stays comparable.
    assert event.finished_at.tzinfo is not None
    assert (datetime.now(timezone.utc) - event.finished_at).total_seconds() < 5


@pytest.mark.asyncio
async def test_commits_terminal_once_even_if_job_rows_updated_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the job status changed between the read and the commit (e.g. a
    watchdog flipped it to FAILED), the TerminalCommitResult reports
    `job_rows_updated == 0`. The duplicate-guard must still report the
    Decision so the caller can log + skip the work; it must not retry
    or raise."""
    from intric.worker.crawl import duplicate_guard

    primary_job_id = uuid4()
    session = _FakeSession(primary_job_id=primary_job_id)

    async def commit_with_zero_rows(session: _FakeSession, event: Any) -> Any:
        session.terminal_events_committed.append(event)

        class _Result:
            crawl_run_rows_updated = 0
            job_rows_updated = 0

        return _Result()

    monkeypatch.setattr(duplicate_guard, "commit_terminal", commit_with_zero_rows)

    decision = await try_duplicate_skip(
        session_scope=_make_session_scope(session),
        job_id=uuid4(),
        run_id=uuid4(),
        website_id=uuid4(),
    )

    assert decision is not None
    assert decision.primary_job_id == primary_job_id
    assert len(session.terminal_events_committed) == 1
