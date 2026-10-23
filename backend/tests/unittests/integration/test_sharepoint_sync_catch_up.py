"""The periodic catch-up queues what notifications alone would have missed."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.integration.infrastructure import sharepoint_subscription_worker
from eneo.integration.infrastructure.sharepoint_subscription_worker import (
    catch_up_sharepoint_syncs,
)
from eneo.integration.infrastructure.sharepoint_sync_keys import (
    sync_catch_up_key,
    sync_catch_up_marker_key,
    sync_lock_key,
    sync_pending_full_key,
    sync_pending_key,
    sync_queued_key,
)
from eneo.integration.infrastructure.sharepoint_webhook_service import (
    SharepointWebhookService,
    _CatchUpCandidate,  # pyright: ignore[reportPrivateUsage]
)
from eneo.jobs.job_models import Task

NOW = datetime.now(timezone.utc)
STALE_BEFORE = NOW - timedelta(hours=6)
WINDOW = 6 * 3600


class _Pipeline:
    def __init__(self, store: dict[str, str]) -> None:
        self.store = store
        self.keys: list[str] = []

    async def __aenter__(self) -> "_Pipeline":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def exists(self, key: str) -> "_Pipeline":
        self.keys.append(key)
        return self

    async def execute(self) -> list[int]:
        return [1 if key in self.store else 0 for key in self.keys]


class _Redis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def pipeline(self, transaction: bool = True) -> _Pipeline:
        return _Pipeline(self.store)

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True


def _candidate(*, hours_ago: float, delta_token: bool = True) -> _CatchUpCandidate:
    return _CatchUpCandidate(
        id=uuid4(),
        has_delta_token=delta_token,
        last_activity=NOW - timedelta(hours=hours_ago),
    )


@pytest.fixture
def redis() -> _Redis:
    return _Redis()


class _Session:
    """Transactions as the catch-up opens them, one per source."""

    def __init__(self) -> None:
        self.transactions = 0

    def begin(self):
        session = self

        class Transaction:
            async def __aenter__(self):
                session.transactions += 1
                return self

            async def __aexit__(self, *_):
                return False

        return Transaction()


@pytest.fixture
def service(redis) -> SharepointWebhookService:
    service = SharepointWebhookService(
        session=_Session(),  # pyright: ignore[reportArgumentType]
        oauth_token_repo=AsyncMock(),
        job_repo=AsyncMock(),
        user_repo=AsyncMock(),
        change_key_service=AsyncMock(),
        sharepoint_subscription_repo=AsyncMock(),
        redis_client=redis,  # pyright: ignore[reportArgumentType]
    )
    return service


def _with_candidates(service, candidates: list[_CatchUpCandidate]) -> AsyncMock:
    service._catch_up_candidates = AsyncMock(return_value=candidates)

    async def fetch(condition):
        # The catch-up asks for one knowledge row at a time, by id.
        wanted = condition.right.value
        return [
            (MagicMock(id=candidate.id), MagicMock())
            for candidate in candidates
            if candidate.id == wanted
        ]

    service._fetch_knowledge = fetch
    queue = AsyncMock(return_value=Task.SYNC_SHAREPOINT_DELTA)
    service._queue_sync = queue
    return queue


def _queued_ids(queue: AsyncMock) -> list:
    return [call.args[0].id for call in queue.await_args_list]


async def _catch_up(service, *, limit: int = 25) -> dict[str, int]:
    return await service.queue_catch_up_syncs(
        stale_before=STALE_BEFORE, limit=limit, window_seconds=WINDOW
    )


async def test_a_source_without_a_recent_sync_gets_a_delta_sync(service, redis):
    stale = _candidate(hours_ago=7)
    fresh = _candidate(hours_ago=1)
    queue = _with_candidates(service, [stale, fresh])

    summary = await _catch_up(service)

    assert _queued_ids(queue) == [stale.id]
    assert queue.await_args.kwargs["full"] is False
    assert summary == {"queued": 1, "markers": 0, "stale": 1}
    assert redis.ttls[sync_catch_up_key(str(stale.id))] == WINDOW


async def test_a_source_without_a_delta_token_is_left_to_its_next_notification(
    service,
):
    """A full sync of a whole library is not something to schedule blindly."""
    queue = _with_candidates(service, [_candidate(hours_ago=48, delta_token=False)])

    await _catch_up(service)

    queue.assert_not_awaited()


@pytest.mark.parametrize("key", [sync_lock_key, sync_queued_key])
async def test_a_running_or_queued_sync_is_not_doubled(service, redis, key):
    stale = _candidate(hours_ago=7)
    redis.store[sync_pending_key(str(stale.id))] = "1"
    redis.store[key(str(stale.id))] = "1"
    queue = _with_candidates(service, [stale])

    await _catch_up(service)

    queue.assert_not_awaited()


async def test_a_source_caught_up_within_the_window_is_not_queued_again(service, redis):
    """A source whose catch-up sync failed early would otherwise be queued on
    every run."""
    stale = _candidate(hours_ago=30)
    redis.store[sync_catch_up_key(str(stale.id))] = "1"
    queue = _with_candidates(service, [stale])

    await _catch_up(service)

    queue.assert_not_awaited()


@pytest.mark.parametrize(
    ("marker", "full"), [(sync_pending_key, False), (sync_pending_full_key, True)]
)
async def test_an_unread_marker_gets_its_sync_however_recent_the_last_one(
    service, redis, marker, full
):
    recent = _candidate(hours_ago=0.5, delta_token=False)
    redis.store[marker(str(recent.id))] = "1"
    queue = _with_candidates(service, [recent])

    summary = await _catch_up(service)

    assert _queued_ids(queue) == [recent.id]
    assert queue.await_args.kwargs["full"] is full
    assert summary == {"queued": 1, "markers": 1, "stale": 0}
    assert sync_catch_up_key(str(recent.id)) not in redis.store
    assert redis.ttls[sync_catch_up_marker_key(str(recent.id))] == 3600


async def test_a_marker_retried_within_its_window_waits(service, redis):
    """A marker whose source cannot be queued (no tenant admin, no token)
    would otherwise take a place in every run."""
    marked = _candidate(hours_ago=0.5)
    redis.store[sync_pending_key(str(marked.id))] = "1"
    redis.store[sync_catch_up_marker_key(str(marked.id))] = "1"
    queue = _with_candidates(service, [marked])

    await _catch_up(service)

    queue.assert_not_awaited()


async def test_a_source_that_fails_to_queue_holds_up_neither_others_nor_later_runs(
    service, redis
):
    broken = _candidate(hours_ago=0.5)
    redis.store[sync_pending_key(str(broken.id))] = "1"
    stale = _candidate(hours_ago=30)
    queue = _with_candidates(service, [broken, stale])

    async def queue_sync(knowledge_db, _connection, **_kwargs):
        if knowledge_db.id == broken.id:
            raise RuntimeError("MultipleResultsFound on the OAuth token")
        return Task.SYNC_SHAREPOINT_DELTA

    queue.side_effect = queue_sync

    first = await _catch_up(service)
    second = await _catch_up(service)

    assert first == {"queued": 1, "markers": 0, "stale": 1}
    assert second == {"queued": 0, "markers": 0, "stale": 0}
    assert _queued_ids(queue) == [broken.id, stale.id]
    # Each run's listing, and one transaction per source attempted.
    assert service.session.transactions == (1 + 2) + 1  # pyright: ignore[reportAttributeAccessIssue]


async def test_a_run_is_bounded_markers_first_then_the_longest_unsynced(service, redis):
    marked = _candidate(hours_ago=0.5)
    redis.store[sync_pending_key(str(marked.id))] = "1"
    older = _candidate(hours_ago=50)
    oldest = _candidate(hours_ago=90)
    old = _candidate(hours_ago=10)
    queue = _with_candidates(service, [old, older, marked, oldest])

    summary = await _catch_up(service, limit=3)

    assert _queued_ids(queue) == [marked.id, oldest.id, older.id]
    assert summary == {"queued": 3, "markers": 1, "stale": 2}


async def test_a_source_that_could_not_be_queued_is_not_counted(service):
    stale = _candidate(hours_ago=7)
    queue = _with_candidates(service, [stale])
    queue.return_value = None

    summary = await _catch_up(service)

    assert summary == {"queued": 0, "markers": 0, "stale": 0}


async def test_the_cron_uses_the_configured_window(monkeypatch):
    monkeypatch.setattr(
        sharepoint_subscription_worker,
        "get_settings",
        lambda: SimpleNamespace(
            sharepoint_catch_up_after_hours=4,
            sharepoint_catch_up_max_syncs_per_run=10,
        ),
    )
    container = MagicMock()
    queue = AsyncMock(return_value={"queued": 2, "markers": 1, "stale": 1})
    container.sharepoint_webhook_service.return_value.queue_catch_up_syncs = queue

    summary = await catch_up_sharepoint_syncs.__wrapped__(container=container)

    assert summary["queued"] == 2
    kwargs = queue.await_args.kwargs
    assert kwargs["limit"] == 10
    assert kwargs["window_seconds"] == 4 * 3600
    expected = datetime.now(timezone.utc) - timedelta(hours=4)
    assert abs((kwargs["stale_before"] - expected).total_seconds()) < 60


async def test_the_cron_does_nothing_when_turned_off(monkeypatch):
    monkeypatch.setattr(
        sharepoint_subscription_worker,
        "get_settings",
        lambda: SimpleNamespace(
            sharepoint_catch_up_after_hours=0,
            sharepoint_catch_up_max_syncs_per_run=10,
        ),
    )
    container = MagicMock()

    summary = await catch_up_sharepoint_syncs.__wrapped__(container=container)

    assert summary["queued"] == 0
    container.sharepoint_webhook_service.assert_not_called()
