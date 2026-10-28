"""SharePoint sync tasks: a webhook that loses the lease race is not dropped."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.integration.infrastructure.sharepoint_sync_keys import (
    SHAREPOINT_SYNC_PENDING_TTL_SECONDS,
)
from eneo.integration.tasks import integration_task

KNOWLEDGE_ID = uuid4()
LOCK_KEY = f"sharepoint_sync_lock:{KNOWLEDGE_ID}"
PENDING_KEY = f"sharepoint_sync_pending:{KNOWLEDGE_ID}"
PENDING_FULL_KEY = f"sharepoint_sync_pending_full:{KNOWLEDGE_ID}"
QUEUED_KEY = f"sharepoint_sync_queued:{KNOWLEDGE_ID}"


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

    async def exists(self, *keys):
        return sum(1 for key in keys if key in self.store)

    async def delete(self, *keys):
        return sum(1 for key in keys if self.store.pop(key, None) is not None)

    async def close(self):
        self.closed = True


@pytest.fixture
def follow_ups(monkeypatch):
    """The jobs queued once a lease is released: (knowledge id, full)."""
    queue = AsyncMock()
    monkeypatch.setattr(integration_task, "_queue_sync_job", queue)
    return queue


@pytest.fixture
def fake_redis(monkeypatch, follow_ups):
    redis = FakeRedis()
    monkeypatch.setattr(integration_task, "_open_redis", AsyncMock(return_value=redis))

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
    assert fake_redis.ttls[PENDING_KEY] == SHAREPOINT_SYNC_PENDING_TTL_SECONDS
    assert fake_redis.store[LOCK_KEY] == "someone-else"
    assert fake_redis.closed


def _marker_lands_during_the_sync(fake_redis, service, *, in_delta=True) -> None:
    """A notification arrives while the task's own sync runs."""

    async def full_sync(**_):
        fake_redis.store[PENDING_KEY] = "1"
        return "Imported 3 files"

    passes = 0

    async def delta(**_):
        nonlocal passes
        passes += 1
        if in_delta and passes == 1:
            fake_redis.store[PENDING_KEY] = "1"
        return "Imported 1 file"

    service.pull_content.side_effect = full_sync
    service.process_delta_changes.side_effect = delta


@pytest.mark.parametrize("task", [delta_task, full_task], ids=["delta", "full"])
async def test_lease_holder_runs_the_pending_pass_before_releasing(
    fake_redis, service, container, params, task, follow_ups
):
    _marker_lands_during_the_sync(fake_redis, service, in_delta=task is delta_task)
    held_during_passes: list[bool] = []
    original = service.process_delta_changes.side_effect

    async def record(**kwargs):
        held_during_passes.append(LOCK_KEY in fake_redis.store)
        return await original(**kwargs)

    service.process_delta_changes.side_effect = record

    await task(params, container)

    expected_delta_passes = 2 if task is delta_task else 1
    assert service.process_delta_changes.await_count == expected_delta_passes
    assert [
        call.kwargs["record_failure"]
        for call in service.process_delta_changes.await_args_list
    ] == [True] * (expected_delta_passes - 1) + [False]
    assert held_during_passes[-1] is True
    assert PENDING_KEY not in fake_redis.store
    assert LOCK_KEY not in fake_redis.store
    follow_ups.assert_not_awaited()


@pytest.mark.parametrize("task", [delta_task, full_task], ids=["delta", "full"])
async def test_a_marker_left_before_the_sync_started_is_served_by_its_pass(
    fake_redis, service, container, params, task, follow_ups
):
    fake_redis.store[PENDING_KEY] = "1"

    await task(params, container)

    expected_delta_passes = 1 if task is delta_task else 0
    assert service.process_delta_changes.await_count == expected_delta_passes
    assert PENDING_KEY not in fake_redis.store
    follow_ups.assert_not_awaited()


async def test_no_pending_marker_means_a_single_pass(
    fake_redis, service, container, params
):
    await delta_task(params, container)

    service.process_delta_changes.assert_awaited_once()
    assert PENDING_KEY not in fake_redis.store


@pytest.mark.parametrize(
    ("task", "marker"),
    [
        pytest.param(delta_task, PENDING_KEY, id="delta"),
        pytest.param(full_task, PENDING_FULL_KEY, id="full"),
    ],
)
async def test_a_task_that_cannot_leave_its_marker_fails_its_job(
    fake_redis, service, container, params, monkeypatch, task, marker
):
    """The lease holder would never hear of the change; the job must not
    report it handled."""
    fake_redis.store[LOCK_KEY] = "someone-else"
    original_set = fake_redis.set

    async def refuse_the_marker(key, value, nx=False, ex=None):
        if key == marker:
            raise RedisConnectionError("refused")
        return await original_set(key, value, nx=nx, ex=ex)

    monkeypatch.setattr(fake_redis, "set", refuse_the_marker)

    with pytest.raises(integration_task.IntegrationSyncError):
        await task(params, container)

    service.process_delta_changes.assert_not_called()
    service.pull_content.assert_not_called()
    assert fake_redis.closed


async def test_holder_released_before_retry_so_the_marker_is_drained_now(
    fake_redis, service, container, params, monkeypatch
):
    fake_redis.store[LOCK_KEY] = "someone-else"
    _release_after_first_refusal(fake_redis, monkeypatch)

    result = await delta_task(params, container)

    assert result == "Imported 1 file"
    service.process_delta_changes.assert_awaited_once()
    assert PENDING_KEY not in fake_redis.store
    assert LOCK_KEY not in fake_redis.store


def _release_after_first_refusal(fake_redis, monkeypatch) -> None:
    original_set = fake_redis.set

    async def release(key, value, nx=False, ex=None):
        acquired = await original_set(key, value, nx=nx, ex=ex)
        if key == LOCK_KEY and not acquired:
            fake_redis.store.pop(LOCK_KEY)
        return acquired

    monkeypatch.setattr(fake_redis, "set", release)


async def test_a_pass_run_on_the_retried_lease_is_an_ordinary_recorded_one(
    fake_redis, service, container, params, monkeypatch
):
    """No sync owns the lease the retry took, so nobody else records the pass."""
    fake_redis.store[LOCK_KEY] = "someone-else"
    _release_after_first_refusal(fake_redis, monkeypatch)

    await delta_task(params, container)

    assert service.process_delta_changes.await_args.kwargs["record_failure"] is True


async def test_a_failing_pass_on_the_retried_lease_fails_the_job(
    fake_redis, service, container, params, monkeypatch
):
    fake_redis.store[LOCK_KEY] = "someone-else"
    _release_after_first_refusal(fake_redis, monkeypatch)
    service.process_delta_changes.side_effect = RuntimeError("Graph 503")

    with pytest.raises(integration_task.IntegrationSyncError, match="Graph 503"):
        await delta_task(params, container)

    service.process_delta_changes.assert_awaited_once()
    assert service.process_delta_changes.await_args.kwargs["record_failure"] is True
    # The failure is the knowledge's status and the kept token replays the
    # change; a marker would only add an empty pass to the next sync.
    assert PENDING_KEY not in fake_redis.store
    assert LOCK_KEY not in fake_redis.store


async def test_failing_pending_pass_keeps_the_marker_for_a_follow_up(
    fake_redis, service, container, params, follow_ups
):
    _marker_lands_during_the_sync(fake_redis, service)
    service.process_delta_changes.side_effect = RuntimeError("Graph 503")

    result = await full_task(params, container)

    assert result == "Imported 3 files"
    service.process_delta_changes.assert_awaited_once()
    assert service.process_delta_changes.await_args.kwargs["record_failure"] is False
    assert fake_redis.store[PENDING_KEY] == "1"
    assert fake_redis.ttls[PENDING_KEY] == SHAREPOINT_SYNC_PENDING_TTL_SECONDS
    assert LOCK_KEY not in fake_redis.store
    follow_ups.assert_awaited_once_with(KNOWLEDGE_ID, full=False)


async def test_drain_is_bounded_when_markers_keep_arriving(
    fake_redis, service, container, params, follow_ups
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
    # The work past the cap is queued as a job of its own, not dropped.
    follow_ups.assert_awaited_once_with(KNOWLEDGE_ID, full=False)


async def test_a_marker_without_a_delta_token_queues_one_full_sync_after_the_lease(
    fake_redis, service, container, params, knowledge, follow_ups
):
    _marker_lands_during_the_sync(fake_redis, service)
    knowledge.delta_token = None

    result = await full_task(params, container)

    assert result == "Imported 3 files"
    service.pull_content.assert_awaited_once()
    service.process_delta_changes.assert_not_called()
    assert fake_redis.store[PENDING_KEY] == "1"
    # The follow-up picks a full sync because there is no token to delta from.
    follow_ups.assert_awaited_once_with(KNOWLEDGE_ID, full=False)


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


def _signed_download_error() -> Exception:
    return RuntimeError(
        "403, message='Forbidden', url='https://contoso.sharepoint.com/sites/KS/"
        "_layouts/15/download.aspx?UniqueId=abc&tempauth=v1.eyJhdWQiOiJ4In0.c2ln'"
    )


@pytest.mark.parametrize("task", [delta_task, full_task], ids=["delta", "full"])
async def test_a_failed_sync_reports_no_url_to_its_job(
    fake_redis, service, container, params, task
):
    failure = _signed_download_error()
    service.pull_content.side_effect = failure
    service.process_delta_changes.side_effect = failure

    with pytest.raises(integration_task.IntegrationSyncError) as caught:
        await task(params, container)

    # The job stores str() of what the task raised.
    assert str(caught.value) == "HTTP 403 Forbidden"
    assert caught.value.__cause__ is failure
    assert LOCK_KEY not in fake_redis.store


async def test_a_failed_confluence_sync_reports_no_url_to_its_job(monkeypatch):
    failure = _signed_download_error()
    monkeypatch.setattr(
        integration_task,
        "_get_knowledge_with_retry",
        AsyncMock(return_value=MagicMock(id=KNOWLEDGE_ID)),
    )
    monkeypatch.setattr(integration_task, "_validate_embedding_provider", AsyncMock())
    container = MagicMock()
    container.confluence_content_service.return_value.pull_content = AsyncMock(
        side_effect=failure
    )
    confluence_task = integration_task.pull_confluence_content.__wrapped__

    with pytest.raises(integration_task.IntegrationSyncError) as caught:
        await confluence_task(
            SimpleNamespace(
                integration_knowledge_id=KNOWLEDGE_ID,
                token_id=uuid4(),
                space_key="DOCS",
            ),
            container,
        )

    assert str(caught.value) == "HTTP 403 Forbidden"
    assert caught.value.__cause__ is failure


@pytest.mark.parametrize("task", [delta_task, full_task], ids=["delta", "full"])
@pytest.mark.parametrize("outcome", ["commit", "rollback"])
async def test_lease_is_held_until_the_tasks_transaction_has_ended(
    fake_redis, service, container, params, task, outcome
):
    """The worker commits after the task returns; the next holder must not
    read this sync's rows before they are visible."""
    session = AsyncSession()
    container.session.return_value = session
    held_after_return = None
    try:
        async with session.begin():
            await task(params, container)
            held_after_return = LOCK_KEY in fake_redis.store
            if outcome == "rollback":
                raise RuntimeError("commit refused")
    except RuntimeError:
        pass
    for _ in range(5):
        if LOCK_KEY not in fake_redis.store:
            break
        await asyncio.sleep(0)
    await session.close()

    assert held_after_return is True
    assert LOCK_KEY not in fake_redis.store
    assert fake_redis.closed


async def _run_in_transaction(task, params, container, *, before_commit=None):
    session = AsyncSession()
    container.session.return_value = session
    try:
        async with session.begin():
            result = await task(params, container)
            if before_commit is not None:
                before_commit()
    finally:
        for _ in range(5):
            await asyncio.sleep(0)
        await session.close()
    return result


@pytest.mark.parametrize("task", [delta_task, full_task], ids=["delta", "full"])
async def test_a_marker_left_after_the_last_drain_is_queued_after_the_release(
    fake_redis, service, container, params, task, follow_ups
):
    """A notification between the holder's last pending pass and the release
    of the lease sees the lease held and only leaves a marker."""

    def notification_arrives() -> None:
        assert LOCK_KEY in fake_redis.store
        fake_redis.store[PENDING_KEY] = "1"

    await _run_in_transaction(
        task, params, container, before_commit=notification_arrives
    )

    assert LOCK_KEY not in fake_redis.store
    follow_ups.assert_awaited_once_with(KNOWLEDGE_ID, full=False)


@pytest.mark.parametrize("task", [delta_task, full_task], ids=["delta", "full"])
async def test_a_failed_sync_leaves_the_markers_set_during_it_to_a_follow_up(
    fake_redis, service, container, params, task, follow_ups
):
    async def fails_after_a_notification(**_):
        fake_redis.store[PENDING_KEY] = "1"
        raise RuntimeError("Graph 502")

    service.pull_content.side_effect = fails_after_a_notification
    service.process_delta_changes.side_effect = fails_after_a_notification

    with pytest.raises(integration_task.IntegrationSyncError):
        await task(params, container)

    follow_ups.assert_awaited_once_with(KNOWLEDGE_ID, full=False)


@pytest.mark.parametrize("task", [delta_task, full_task], ids=["delta", "full"])
async def test_a_job_failing_before_its_pass_does_not_queue_itself_again(
    fake_redis, service, container, params, task, follow_ups, monkeypatch
):
    fake_redis.store[PENDING_KEY] = "1"
    monkeypatch.setattr(
        integration_task,
        "_validate_embedding_provider",
        AsyncMock(side_effect=ValueError("provider inactive")),
    )

    with pytest.raises(integration_task.IntegrationSyncError):
        await task(params, container)

    follow_ups.assert_not_awaited()


@pytest.mark.parametrize("task", [delta_task, full_task], ids=["delta", "full"])
async def test_a_starting_task_clears_the_queued_sync_marker(
    fake_redis, service, container, params, task
):
    fake_redis.store[QUEUED_KEY] = "1"
    fake_redis.store[LOCK_KEY] = "someone-else"

    await task(params, container)

    assert QUEUED_KEY not in fake_redis.store


async def test_a_full_sync_blocked_by_a_running_sync_is_deferred_not_skipped(
    fake_redis, service, container, params, follow_ups
):
    fake_redis.store[LOCK_KEY] = "someone-else"

    result = await full_task(params, container)

    assert result == integration_task.DEFERRED_FULL_SYNC_RESULT
    service.pull_content.assert_not_called()
    assert fake_redis.store[PENDING_FULL_KEY] == "1"
    assert fake_redis.ttls[PENDING_FULL_KEY] == SHAREPOINT_SYNC_PENDING_TTL_SECONDS
    assert fake_redis.store[LOCK_KEY] == "someone-else"
    follow_ups.assert_not_awaited()


async def test_the_holder_queues_the_full_sync_asked_for_during_its_delta(
    fake_redis, service, container, params, follow_ups
):
    async def manual_full_sync_arrives(**_):
        fake_redis.store[PENDING_FULL_KEY] = "1"
        return "Imported 1 file"

    service.process_delta_changes.side_effect = manual_full_sync_arrives

    await delta_task(params, container)

    follow_ups.assert_awaited_once_with(KNOWLEDGE_ID, full=True)


async def test_a_full_sync_whose_holder_released_meanwhile_runs_now(
    fake_redis, service, container, params, follow_ups, monkeypatch
):
    fake_redis.store[LOCK_KEY] = "someone-else"
    _release_after_first_refusal(fake_redis, monkeypatch)

    result = await full_task(params, container)

    assert result == "Imported 3 files"
    service.pull_content.assert_awaited_once()
    assert PENDING_FULL_KEY not in fake_redis.store
    follow_ups.assert_not_awaited()


async def test_a_full_sync_serves_the_full_sync_markers_left_before_it(
    fake_redis, service, container, params, follow_ups
):
    fake_redis.store[PENDING_FULL_KEY] = "1"

    await full_task(params, container)

    assert PENDING_FULL_KEY not in fake_redis.store
    follow_ups.assert_not_awaited()


async def test_a_follow_up_that_cannot_be_queued_still_closes_redis(
    fake_redis, service, container, params, follow_ups
):
    follow_ups.side_effect = RuntimeError("database down")

    async def notification(**_):
        fake_redis.store[PENDING_KEY] = "1"
        raise RuntimeError("Graph 502")

    service.process_delta_changes.side_effect = notification

    with pytest.raises(integration_task.IntegrationSyncError):
        await delta_task(params, container)

    assert fake_redis.closed
    assert LOCK_KEY not in fake_redis.store


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


@pytest.mark.parametrize("task", [delta_task, full_task], ids=["delta", "full"])
async def test_a_sync_links_its_knowledge_to_the_sites_subscription(
    fake_redis, service, container, params, knowledge, task
):
    """An import or resync skips the link while a sync holds the row."""
    knowledge.sharepoint_subscription_id = None
    knowledge.site_id = "site-1"
    subscription = MagicMock(id=uuid4())
    container.session.return_value.begin_nested = MagicMock(return_value=_Savepoint())
    container.sharepoint_subscription_repo.return_value.get_by_user_and_site = (
        AsyncMock(return_value=subscription)
    )
    link = AsyncMock(return_value=True)
    container.integration_knowledge_repo.return_value.link_subscription = link

    await task(params, container)

    container.sharepoint_subscription_repo.return_value.get_by_user_and_site.assert_awaited_once_with(
        user_integration_id=knowledge.user_integration.id, site_id="site-1"
    )
    link.assert_awaited_once_with(KNOWLEDGE_ID, subscription.id)
    assert knowledge.sharepoint_subscription_id == subscription.id


async def test_a_failing_link_does_not_fail_the_sync(
    fake_redis, service, container, params, knowledge
):
    knowledge.sharepoint_subscription_id = None
    knowledge.site_id = "site-1"
    container.session.return_value.begin_nested = MagicMock(return_value=_Savepoint())
    container.sharepoint_subscription_repo.return_value.get_by_user_and_site = (
        AsyncMock(side_effect=RuntimeError("database hiccup"))
    )

    assert await delta_task(params, container) == "Imported 1 file"
