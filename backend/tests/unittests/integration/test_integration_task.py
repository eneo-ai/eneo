"""SharePoint sync tasks: a webhook that loses the lease race is not dropped."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.integration.tasks import integration_task

KNOWLEDGE_ID = uuid4()
LOCK_KEY = f"sharepoint_sync_lock:{KNOWLEDGE_ID}"
PENDING_KEY = f"sharepoint_sync_pending:{KNOWLEDGE_ID}"


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.closed = False

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0

    async def close(self):
        self.closed = True


@pytest.fixture
def fake_redis(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(integration_task, "_open_redis", AsyncMock(return_value=redis))
    monkeypatch.setattr(integration_task, "_PENDING_RETRY_DELAY_SECONDS", 0)

    @asynccontextmanager
    async def lease(redis_client, key, *, ttl_seconds, **_):
        acquired = bool(await redis_client.set(key, "owner", nx=True, ex=ttl_seconds))
        try:
            yield acquired
        finally:
            if acquired:
                await redis_client.delete(key)

    monkeypatch.setattr(integration_task, "redis_lease", lease)
    return redis


@pytest.fixture
def knowledge():
    return MagicMock(id=KNOWLEDGE_ID, delta_token="delta-token")


@pytest.fixture
def service(monkeypatch, knowledge):
    service = AsyncMock()
    service.pull_content.return_value = "Imported 3 files"
    service.process_delta_changes.return_value = "Imported 1 file"
    monkeypatch.setattr(
        integration_task,
        "_get_knowledge_with_retry",
        AsyncMock(return_value=knowledge),
    )
    monkeypatch.setattr(integration_task, "_validate_embedding_provider", AsyncMock())
    return service


@pytest.fixture
def container(service, knowledge):
    container = MagicMock()
    container.sharepoint_content_service.return_value = service
    container.integration_knowledge_repo.return_value.one = AsyncMock(
        return_value=knowledge
    )
    return container


@pytest.fixture
def params():
    return SimpleNamespace(
        integration_knowledge_id=KNOWLEDGE_ID,
        token_id=uuid4(),
        tenant_app_id=None,
        site_id="site-1",
        drive_id="drive-1",
        folder_id=None,
        folder_path=None,
        resource_type="site",
    )


# The decorated tasks are ARQ wrappers; the task bodies are reachable via __wrapped__.
delta_task = integration_task.sync_sharepoint_delta.__wrapped__
full_task = integration_task.pull_sharepoint_content.__wrapped__


async def test_delta_blocked_by_a_running_sync_leaves_a_pending_marker(
    fake_redis, service, container, params
):
    fake_redis.store[LOCK_KEY] = "someone-else"

    result = await delta_task(params, container)

    assert result.startswith("Skipped")
    service.process_delta_changes.assert_not_called()
    assert fake_redis.store[PENDING_KEY] == "1"
    assert fake_redis.ttls[PENDING_KEY] == 3600
    assert fake_redis.store[LOCK_KEY] == "someone-else"
    assert fake_redis.closed


@pytest.mark.parametrize("task", [delta_task, full_task], ids=["delta", "full"])
async def test_lease_holder_runs_the_pending_pass_before_releasing(
    fake_redis, service, container, params, task
):
    fake_redis.store[PENDING_KEY] = "1"
    seen_during_pending: list[bool] = []

    async def record(**_):
        seen_during_pending.append(LOCK_KEY in fake_redis.store)
        return "Imported 1 file"

    service.process_delta_changes.side_effect = record

    await task(params, container)

    expected_delta_passes = 2 if task is delta_task else 1
    assert service.process_delta_changes.await_count == expected_delta_passes
    assert seen_during_pending[-1] is True
    assert PENDING_KEY not in fake_redis.store
    assert LOCK_KEY not in fake_redis.store


async def test_no_pending_marker_means_a_single_pass(
    fake_redis, service, container, params
):
    await delta_task(params, container)

    service.process_delta_changes.assert_awaited_once()
    assert PENDING_KEY not in fake_redis.store


async def test_holder_released_before_retry_so_the_marker_is_drained_now(
    fake_redis, service, container, params, monkeypatch
):
    fake_redis.store[LOCK_KEY] = "someone-else"
    original_set = fake_redis.set

    async def release_after_first_refusal(key, value, nx=False, ex=None):
        acquired = await original_set(key, value, nx=nx, ex=ex)
        if key == LOCK_KEY and not acquired:
            fake_redis.store.pop(LOCK_KEY)
        return acquired

    monkeypatch.setattr(fake_redis, "set", release_after_first_refusal)

    result = await delta_task(params, container)

    assert result == "Imported 1 file"
    service.process_delta_changes.assert_awaited_once()
    assert PENDING_KEY not in fake_redis.store
    assert LOCK_KEY not in fake_redis.store


async def test_failing_pending_pass_keeps_the_marker_for_the_next_sync(
    fake_redis, service, container, params
):
    fake_redis.store[PENDING_KEY] = "1"
    service.process_delta_changes.side_effect = RuntimeError("Graph 503")

    result = await full_task(params, container)

    assert result == "Imported 3 files"
    service.process_delta_changes.assert_awaited_once()
    assert fake_redis.store[PENDING_KEY] == "1"
    assert fake_redis.ttls[PENDING_KEY] == 3600
    assert LOCK_KEY not in fake_redis.store


async def test_drain_is_bounded_when_markers_keep_arriving(
    fake_redis, service, container, params
):
    fake_redis.store[PENDING_KEY] = "1"

    async def webhook_lands_during_every_pass(**_):
        fake_redis.store[PENDING_KEY] = "1"
        return "Imported 1 file"

    service.process_delta_changes.side_effect = webhook_lands_during_every_pass

    await delta_task(params, container)

    assert service.process_delta_changes.await_count == 1 + 3
    assert fake_redis.store[PENDING_KEY] == "1"
    assert LOCK_KEY not in fake_redis.store


async def test_full_sync_without_a_delta_token_does_not_run_a_second_full_sync(
    fake_redis, service, container, params, knowledge
):
    fake_redis.store[PENDING_KEY] = "1"
    knowledge.delta_token = None

    result = await full_task(params, container)

    assert result == "Imported 3 files"
    service.pull_content.assert_awaited_once()
    service.process_delta_changes.assert_not_called()
    assert PENDING_KEY not in fake_redis.store


async def test_waiter_whose_marker_was_drained_has_nothing_to_prepare(
    fake_redis, service, container, params, monkeypatch
):
    fake_redis.store[LOCK_KEY] = "someone-else"
    original_set = fake_redis.set

    async def holder_drains_then_releases(key, value, nx=False, ex=None):
        acquired = await original_set(key, value, nx=nx, ex=ex)
        if key == PENDING_KEY:
            # The holder drains the marker we just left, then releases.
            fake_redis.store.pop(PENDING_KEY)
            fake_redis.store.pop(LOCK_KEY)
        return acquired

    monkeypatch.setattr(fake_redis, "set", holder_drains_then_releases)
    monkeypatch.setattr(
        integration_task,
        "_validate_embedding_provider",
        AsyncMock(side_effect=ValueError("provider inactive")),
    )

    result = await delta_task(params, container)

    assert result.startswith("Skipped")
    service.process_delta_changes.assert_not_called()
    assert LOCK_KEY not in fake_redis.store
