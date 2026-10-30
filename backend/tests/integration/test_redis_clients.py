"""The process's Redis clients against a real Redis.

Requests share the process's pools instead of opening a connection each; the
subscription pool filling up leaves API-key authentication and audit writes
alone; a burst past the command bound queues; stopping closes every connection without help from
the garbage collector, on every event loop; a Redis outage keeps the
configured rate-limit policy.
"""

import asyncio
import contextlib
import gc
import logging
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
import redis.asyncio as aioredis
import redis.exceptions
import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.database.tables.api_keys_v2_table import ApiKeysV2 as ApiKeysV2Table
from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
from eneo.jobs.job_events import job_updates_channel
from eneo.main.config import Settings, get_settings, set_settings
from eneo.main.exceptions import NotReadyException
from eneo.redis.clients import RedisClients, redis_clients
from eneo.redis.rate_limit import build_rate_limit_key
from tests.fixtures import mint_v2_api_key

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_AUTHENTICATED = "/api/v1/jobs/"


async def _connections_received(redis_client: aioredis.Redis) -> int:
    return int((await redis_client.info("stats"))["total_connections_received"])


async def _connected_clients(redis_client: aioredis.Redis) -> int:
    return int((await redis_client.info("clients"))["connected_clients"])


async def _eventually(check: Callable[[], Awaitable[bool]], timeout: float = 5) -> None:
    """Redis drops a closed client asynchronously; wait for it to notice."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not await check():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("Redis did not reach the expected state in time")
        await asyncio.sleep(0.05)


@contextlib.asynccontextmanager
async def _running_with(settings: Settings) -> AsyncIterator[None]:
    """Restart the process's clients on other settings, then restore both."""
    original = get_settings()
    await redis_clients.stop()
    set_settings(settings)
    redis_clients.start()
    try:
        yield
    finally:
        await redis_clients.stop()
        set_settings(original)
        redis_clients.start()


async def _set_rate_limit(key_id: UUID, limit: int) -> None:
    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.update(ApiKeysV2Table)
            .where(ApiKeysV2Table.id == key_id)
            .values(rate_limit=limit)
        )


async def _audit_session_rows(session_id: str) -> int:
    async with sessionmanager.session() as session, session.begin():
        return int(
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(AuditLogTable)
                .where(
                    AuditLogTable.action == "audit_session_created",
                    AuditLogTable.log_metadata["session_id"].astext == session_id,
                )
            )
            or 0
        )


@contextlib.asynccontextmanager
async def _job_event_stream(app: Any, api_key: str) -> AsyncIterator[list[int]]:
    """Hold one real `GET /jobs/events/` stream open until the block ends.

    httpx's ASGI transport buffers a whole response, so the stream is driven
    through the ASGI interface directly; the browser disconnects on exit.
    """
    disconnected = asyncio.Event()
    requested = False
    statuses: list[int] = []

    async def receive() -> dict[str, Any]:
        nonlocal requested
        if not requested:
            requested = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            statuses.append(message["status"])

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/v1/jobs/events/",
        "raw_path": b"/api/v1/jobs/events/",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"test.local"),
            (get_settings().api_key_header_name.lower().encode(), api_key.encode()),
        ],
        "server": ("test.local", 80),
        "client": ("127.0.0.1", 50000),
    }
    stream = asyncio.create_task(app(scope, receive, send))
    try:
        yield statuses
    finally:
        disconnected.set()
        await asyncio.wait_for(stream, timeout=10)


async def test_api_key_requests_open_no_redis_connections_of_their_own(
    client, admin_user_api_key, redis_client
):
    headers = {get_settings().api_key_header_name: admin_user_api_key.key}
    # The first request opens the process pool's connection.
    assert (await client.get(_AUTHENTICATED, headers=headers)).status_code == 200
    before = await _connections_received(redis_client)

    for _ in range(100):
        response = await client.get(_AUTHENTICATED, headers=headers)
        assert response.status_code == 200, response.text

    assert await _connections_received(redis_client) - before == 0


async def test_a_full_subscription_pool_leaves_api_keys_and_audit_writes_alone(
    app, client, db_container, admin_user, admin_user_api_key, redis_client, caplog
):
    streams = 2
    # The streams authenticate with a key of their own, so the limited key
    # spends its whole budget on the requests below.
    async with db_container() as container:
        stream_key = await mint_v2_api_key(
            container.api_key_v2_repo(),
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            prefix="test",
        )
    headers = {get_settings().api_key_header_name: admin_user_api_key.key}
    await _set_rate_limit(admin_user_api_key.id, 2)
    channel = job_updates_channel(admin_user.id)

    async def subscribers() -> int:
        counts = await redis_client.pubsub_numsub(channel)
        return int(counts[0][1])

    # The audit write below must find its config cache empty and its session
    # budget unspent, so it reads and writes through Redis.
    cached_action = f"audit_action:{admin_user.tenant_id}:audit_session_created"
    await redis_client.delete(
        cached_action, build_rate_limit_key(admin_user.id, admin_user.tenant_id)
    )

    bounded = get_settings().model_copy(update={"redis_max_connections": streams})
    async with _running_with(bounded), contextlib.AsyncExitStack() as held:
        for opened in range(1, streams + 1):
            statuses = await held.enter_async_context(
                _job_event_stream(app, stream_key.key)
            )

            async def subscribed(statuses=statuses, opened=opened) -> bool:
                return statuses == [200] and await subscribers() == opened

            await _eventually(subscribed)
        # Negative control: the subscription pool really is at its bound.
        with pytest.raises(redis.exceptions.ConnectionError, match="Too many"):
            await redis_clients.subscriptions().ping()

        first = await client.get(_AUTHENTICATED, headers=headers)
        second = await client.get(_AUTHENTICATED, headers=headers)
        third = await client.get(_AUTHENTICATED, headers=headers)
        # An audit-writing request: its session rate limit, session store and
        # audit config cache all run commands through get_redis().
        with caplog.at_level(logging.WARNING, logger="eneo.audit"):
            audited = await client.post(
                "/api/v1/audit/access-session",
                json={
                    "category": "integration_test",
                    "description": "Audit write while every subscription is held",
                },
                headers={get_settings().api_key_header_name: stream_key.key},
            )

    assert (first.status_code, second.status_code) == (200, 200), first.text
    assert third.status_code == 429, third.text
    assert third.json()["code"] == "rate_limit_exceeded"
    assert third.headers["X-RateLimit-Limit"] == "2"

    assert audited.status_code == 200, audited.text
    assert await _audit_session_rows(audited.cookies["audit_session_id"]) == 1
    # The config was read from and cached in Redis, not fallen back from.
    assert await redis_client.get(cached_action) == b"true"
    degraded = [
        r.getMessage() for r in caplog.records if r.name.startswith("eneo.audit")
    ]
    assert not degraded, degraded


async def test_a_burst_beyond_the_command_bound_waits_instead_of_failing(
    client, admin_user_api_key
):
    """Every request used to get a pool of its own; sharing one bounded pool
    must queue a burst, not turn it into fail-closed 503s."""
    headers = {get_settings().api_key_header_name: admin_user_api_key.key}
    bounded = get_settings().model_copy(update={"redis_max_connections": 1})

    async with _running_with(bounded):
        responses = await asyncio.gather(
            *(client.get(_AUTHENTICATED, headers=headers) for _ in range(100))
        )

    assert [r.status_code for r in responses] == [200] * 100, [
        r.text for r in responses if r.status_code != 200
    ][:1]


async def test_stop_closes_every_connection_without_the_garbage_collector(
    redis_client,
):
    owner = RedisClients()
    baseline = await _connected_clients(redis_client)
    gc.disable()
    try:
        # Two lifecycles in one event loop, as tests that build apps repeatedly do.
        for _ in range(2):
            owner.start()
            await owner.commands().ping()
            await owner.subscriptions().ping()
            # A listener still subscribed at stop, and one cancelled mid-wait.
            straggler = owner.subscriptions().pubsub()
            await straggler.subscribe("redis-clients-test")
            cancelled = owner.subscriptions().pubsub()
            await cancelled.subscribe("redis-clients-test")
            waiting = asyncio.create_task(cancelled.get_message(timeout=None))
            await asyncio.sleep(0.05)
            # Negative control: the clients really hold connections before stop,
            # one command connection and two subscriptions (the first reuses
            # the connection the ping returned to the pool).
            assert await _connected_clients(redis_client) == baseline + 3
            waiting.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await waiting

            await owner.stop()

            async def closed() -> bool:
                return await _connected_clients(redis_client) == baseline

            await _eventually(closed)
            with pytest.raises(NotReadyException):
                owner.commands()
            with pytest.raises(NotReadyException):
                owner.subscriptions()
    finally:
        gc.enable()


async def test_each_lifecycle_connects_on_its_own_event_loop(redis_client):
    """An app built on a fresh event loop gets fresh connections, never ones
    bound to a loop that has since closed."""
    owner = RedisClients()
    baseline = await _connected_clients(redis_client)

    async def serve() -> None:
        owner.start()
        try:
            await owner.commands().ping()
            await owner.subscriptions().ping()
        finally:
            await owner.stop()

    for _ in range(2):
        await asyncio.to_thread(asyncio.run, serve())

    async def closed() -> bool:
        return await _connected_clients(redis_client) == baseline

    await _eventually(closed)


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.mark.parametrize(
    "fail_open, status_code", [(False, 503), (True, 200)], ids=["closed", "open"]
)
async def test_a_redis_outage_keeps_the_configured_rate_limit_policy(
    client, admin_user_api_key, fail_open, status_code
):
    headers = {get_settings().api_key_header_name: admin_user_api_key.key}
    outage = get_settings().model_copy(
        update={
            "redis_host": "127.0.0.1",
            "redis_port": _closed_port(),
            "api_key_rate_limit_fail_open": fail_open,
        }
    )

    async with _running_with(outage):
        response = await client.get(_AUTHENTICATED, headers=headers)

    assert response.status_code == status_code, response.text
    if not fail_open:
        assert response.json()["code"] == "rate_limit_unavailable"
        assert response.json()["message"] == "Rate limiting is temporarily unavailable."
