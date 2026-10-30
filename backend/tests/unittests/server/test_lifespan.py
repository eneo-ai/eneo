import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import eneo.server.dependencies.lifespan as lifespan_module
from eneo.database.database import DatabaseSessionManager
from eneo.object_content.content import (
    ObjectContentConfigurationError,
    ObjectContentUnavailableError,
)
from eneo.object_content.object_store_connection import (
    ObjectStoreConnectionDatabaseUnavailable,
    ObjectStoreConnectionError,
)
from eneo.object_content.runtime import ObjectContentRuntime


@pytest.mark.asyncio
async def test_connection_table_outage_does_not_stop_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        openapi_only_mode=False,
        database_url="postgresql+asyncpg://unused",
        testing=True,
        encryption_key="unused",
    )
    monkeypatch.setattr(lifespan_module, "get_settings", lambda: settings)
    monkeypatch.setattr(lifespan_module.sessionmanager, "init", MagicMock())
    monkeypatch.setattr(lifespan_module.sessionmanager, "close", AsyncMock())
    monkeypatch.setattr(lifespan_module.object_content_runtime, "start", MagicMock())
    monkeypatch.setattr(
        lifespan_module.object_content_runtime,
        "validate_configuration",
        AsyncMock(
            side_effect=ObjectStoreConnectionDatabaseUnavailable(
                "test connection-table outage"
            )
        ),
    )
    monkeypatch.setattr(lifespan_module.object_content_runtime, "stop", AsyncMock())
    monkeypatch.setattr(lifespan_module.redis_clients, "start", MagicMock())
    monkeypatch.setattr(lifespan_module.redis_clients, "stop", AsyncMock())
    monkeypatch.setattr(lifespan_module.aiohttp_client, "start", MagicMock())
    monkeypatch.setattr(lifespan_module.aiohttp_client, "stop", AsyncMock())
    monkeypatch.setattr(lifespan_module.job_manager, "init", AsyncMock())
    monkeypatch.setattr(lifespan_module, "init_predefined_roles", AsyncMock())

    await lifespan_module.startup()

    lifespan_module.object_content_runtime.stop.assert_not_awaited()
    lifespan_module.sessionmanager.close.assert_not_awaited()
    lifespan_module.aiohttp_client.stop.assert_not_awaited()
    lifespan_module.redis_clients.stop.assert_not_awaited()
    lifespan_module.job_manager.init.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_drains_streamed_turns_before_closing_what_they_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The drains run while the loopback internal-MCP servers still answer,
    so a connection host attached to one can end gracefully, and before the
    database pool and HTTP clients close."""
    settings = SimpleNamespace(openapi_only_mode=False)
    monkeypatch.setattr(lifespan_module, "get_settings", lambda: settings)
    order: list[str] = []

    def step(name: str) -> AsyncMock:
        return AsyncMock(side_effect=lambda *a, **k: order.append(name))

    @asynccontextmanager
    async def internal_mcp() -> AsyncIterator[None]:
        order.append("internal-mcp up")
        yield
        order.append("internal-mcp down")

    monkeypatch.setattr(lifespan_module, "startup", step("startup"))
    monkeypatch.setattr(lifespan_module, "internal_mcp_lifespan", internal_mcp)
    monkeypatch.setattr(lifespan_module, "drain_background_saves", step("saves"))
    monkeypatch.setattr(lifespan_module, "drain_connection_hosts", step("mcp"))
    monkeypatch.setattr(lifespan_module.object_content_runtime, "stop", step("objects"))
    monkeypatch.setattr(lifespan_module.sessionmanager, "close", step("db"))
    monkeypatch.setattr(lifespan_module.aiohttp_client, "stop", step("http"))
    monkeypatch.setattr(lifespan_module.job_manager, "close", step("jobs"))
    monkeypatch.setattr(lifespan_module.websocket_manager, "shutdown", step("ws"))

    async with lifespan_module.lifespan(MagicMock()):
        order.append("serving")

    assert order[:3] == ["startup", "internal-mcp up", "serving"]
    assert order.index("saves") < order.index("internal-mcp down")
    assert order.index("mcp") < order.index("internal-mcp down")
    assert order.index("saves") < order.index("db")
    assert order.index("mcp") < order.index("db")
    assert order.index("mcp") < order.index("http")


def _patch_startup_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    order: list[str],
    *,
    validation_error: BaseException | None = None,
    start_error: BaseException | None = None,
    store_stop_error: BaseException | None = None,
    errors: dict[str, BaseException] | None = None,
) -> None:
    settings = SimpleNamespace(
        openapi_only_mode=False,
        database_url="postgresql+asyncpg://unused",
        testing=True,
        encryption_key="unused",
    )
    failing = {
        "runtime.start": start_error,
        "runtime.validate": validation_error,
        "runtime.stop": store_stop_error,
        **(errors or {}),
    }

    def record(name: str) -> AsyncMock:
        async def call(*_: object, **__: object) -> None:
            order.append(name)
            if (error := failing.get(name)) is not None:
                raise error

        return AsyncMock(side_effect=call)

    def record_sync(name: str) -> MagicMock:
        def call(*_: object, **__: object) -> None:
            order.append(name)
            if (error := failing.get(name)) is not None:
                raise error

        return MagicMock(side_effect=call)

    monkeypatch.setattr(lifespan_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        lifespan_module.sessionmanager, "init", record_sync("sessionmanager.init")
    )
    monkeypatch.setattr(
        lifespan_module.sessionmanager, "close", record("sessionmanager.close")
    )
    monkeypatch.setattr(
        lifespan_module.object_content_runtime, "start", record_sync("runtime.start")
    )
    monkeypatch.setattr(
        lifespan_module.object_content_runtime,
        "validate_configuration",
        record("runtime.validate"),
    )
    monkeypatch.setattr(
        lifespan_module.object_content_runtime, "stop", record("runtime.stop")
    )
    monkeypatch.setattr(
        lifespan_module.redis_clients, "start", record_sync("redis.start")
    )
    monkeypatch.setattr(lifespan_module.redis_clients, "stop", record("redis.stop"))
    monkeypatch.setattr(
        lifespan_module.aiohttp_client, "start", record_sync("aiohttp.start")
    )
    monkeypatch.setattr(lifespan_module.aiohttp_client, "stop", record("aiohttp.stop"))
    monkeypatch.setattr(lifespan_module.job_manager, "init", record("jobs.init"))
    monkeypatch.setattr(lifespan_module.job_manager, "close", record("jobs.close"))
    monkeypatch.setattr(lifespan_module, "init_predefined_roles", record("roles"))
    monkeypatch.setattr(
        lifespan_module.websocket_manager, "shutdown", record("websockets.shutdown")
    )


@pytest.mark.asyncio
async def test_startup_and_shutdown_are_persistence_around_the_api_only_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    _patch_startup_dependencies(monkeypatch, order)

    await lifespan_module.startup()
    await lifespan_module.shutdown()

    assert order == [*_STARTED, *_SHUT_DOWN]


_STARTED = [
    "sessionmanager.init",
    "runtime.start",
    "runtime.validate",
    "redis.start",
    "aiohttp.start",
    "jobs.init",
    "roles",
]
# The websocket listeners leave their subscriptions before the Redis clients
# behind them close.
_SHUT_DOWN = [
    "runtime.stop",
    "sessionmanager.close",
    "aiohttp.stop",
    "jobs.close",
    "websockets.shutdown",
    "redis.stop",
]


# What a failed startup stops: only what it started, last started first. A
# step that failed started nothing of its own.
_UNWOUND_AFTER = {
    "redis.start": ["runtime.stop", "sessionmanager.close"],
    "jobs.init": ["aiohttp.stop", "redis.stop", "runtime.stop", "sessionmanager.close"],
    "roles": [
        "jobs.close",
        "aiohttp.stop",
        "redis.stop",
        "runtime.stop",
        "sessionmanager.close",
    ],
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "step, error",
    [
        # Refused: the clients already running are not this startup's to stop.
        ("redis.start", RuntimeError("Redis clients are already running")),
        ("jobs.init", ConnectionError("Redis is unreachable")),
        ("jobs.init", asyncio.CancelledError()),
        ("roles", OSError("the database went away")),
    ],
)
async def test_a_later_startup_failure_stops_only_what_it_started(
    monkeypatch: pytest.MonkeyPatch, step: str, error: BaseException
) -> None:
    """The caller of a failed startup never reaches shutdown, so startup
    unwinds itself, whatever escapes it and cancellation included."""

    order: list[str] = []
    _patch_startup_dependencies(monkeypatch, order, errors={step: error})

    with pytest.raises(type(error)):
        await lifespan_module.startup()

    attempted = _STARTED[: _STARTED.index(step) + 1]
    assert order == [*attempted, *_UNWOUND_AFTER[step]]


@pytest.mark.asyncio
async def test_shutdown_runs_every_step_when_an_earlier_one_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    _patch_startup_dependencies(
        monkeypatch, order, store_stop_error=RuntimeError("the store did not close")
    )

    with pytest.raises(RuntimeError, match="the store did not close"):
        await lifespan_module.shutdown()

    assert order == _SHUT_DOWN


@asynccontextmanager
async def _failing_internal_mcp():
    raise RuntimeError("the internal MCP servers did not start")
    yield


@asynccontextmanager
async def _internal_mcp():
    yield


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "internal_mcp, body_error",
    [
        (_internal_mcp, RuntimeError("the server stopped serving")),
        (_internal_mcp, asyncio.CancelledError()),
        (_failing_internal_mcp, None),
    ],
)
async def test_the_lifespan_shuts_down_however_serving_ends(
    monkeypatch: pytest.MonkeyPatch,
    internal_mcp: Any,
    body_error: BaseException | None,
) -> None:
    order: list[str] = []
    _patch_startup_dependencies(monkeypatch, order)
    monkeypatch.setattr(lifespan_module, "internal_mcp_lifespan", internal_mcp)

    with pytest.raises((RuntimeError, asyncio.CancelledError)):
        async with lifespan_module.lifespan(MagicMock()):
            if body_error is not None:
                raise body_error

    assert order == [*_STARTED, *_SHUT_DOWN]


@pytest.mark.asyncio
async def test_persistence_alone_starts_and_stops_only_the_database_and_object_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    _patch_startup_dependencies(monkeypatch, order)

    await lifespan_module.start_persistence()
    await lifespan_module.stop_persistence()

    assert order == [
        "sessionmanager.init",
        "runtime.start",
        "runtime.validate",
        "runtime.stop",
        "sessionmanager.close",
    ]


@pytest.mark.asyncio
async def test_a_configuration_error_stops_what_persistence_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    error = ObjectContentConfigurationError("store required")
    _patch_startup_dependencies(monkeypatch, order, validation_error=error)

    with pytest.raises(ObjectContentConfigurationError):
        await lifespan_module.startup()

    assert order == [
        "sessionmanager.init",
        "runtime.start",
        "runtime.validate",
        "runtime.stop",
        "sessionmanager.close",
    ]


_STOPPED = ["runtime.stop", "sessionmanager.close"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage, error",
    [
        ("start", RuntimeError("the object-content settings are invalid")),
        ("validate", OSError("the store is unreachable")),
        ("validate", ObjectStoreConnectionError("the connection is unusable")),
        ("validate", asyncio.CancelledError()),
    ],
)
async def test_any_failure_while_starting_leaves_nothing_started(
    monkeypatch: pytest.MonkeyPatch, stage: str, error: BaseException
) -> None:
    """A caller that could not start never reaches its own stop, so the start
    unwinds by itself, whatever escapes it and cancellation included."""

    order: list[str] = []
    _patch_startup_dependencies(
        monkeypatch,
        order,
        start_error=error if stage == "start" else None,
        validation_error=error if stage == "validate" else None,
    )

    with pytest.raises(type(error)):
        await lifespan_module.start_persistence()

    assert order[-2:] == _STOPPED
    lifespan_module.aiohttp_client.stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_transient_object_content_outage_still_leaves_persistence_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    _patch_startup_dependencies(
        monkeypatch,
        order,
        validation_error=ObjectContentUnavailableError("transient outage"),
    )

    await lifespan_module.start_persistence()

    assert order == ["sessionmanager.init", "runtime.start", "runtime.validate"]


@pytest.mark.asyncio
async def test_a_failing_object_store_close_still_disposes_the_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    _patch_startup_dependencies(
        monkeypatch, order, store_stop_error=RuntimeError("the store did not close")
    )

    with pytest.raises(RuntimeError, match="the store did not close"):
        await lifespan_module.stop_persistence()

    assert order == _STOPPED


def _own_singletons(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:
    """Real, private instances of the two singletons: nothing here reaches a database."""

    settings = SimpleNamespace(
        openapi_only_mode=False,
        database_url="postgresql+asyncpg://user:secret@127.0.0.1:1/unused",
        testing=True,
        encryption_key=None,
    )
    manager = DatabaseSessionManager()
    runtime = ObjectContentRuntime(manager)
    monkeypatch.setattr(runtime, "validate_configuration", AsyncMock())
    monkeypatch.setattr(lifespan_module, "get_settings", lambda: settings)
    monkeypatch.setattr(lifespan_module, "sessionmanager", manager)
    monkeypatch.setattr(lifespan_module, "object_content_runtime", runtime)
    return manager, runtime


@pytest.mark.asyncio
async def test_a_second_start_is_refused_and_the_running_owner_stays_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, runtime = _own_singletons(monkeypatch)
    await lifespan_module.start_persistence()

    with pytest.raises(RuntimeError) as refused:
        await lifespan_module.start_persistence()

    # The refusal touched nothing the first start owns.
    assert runtime.enabled
    session = manager.create_session()  # raises once the manager is closed
    await session.close()
    runtime.service  # raises once the runtime is stopped
    assert "already running" in str(refused.value)
    await lifespan_module.stop_persistence()
    assert not runtime.enabled


@pytest.mark.asyncio
async def test_a_failed_start_closes_only_the_database_it_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, runtime = _own_singletons(monkeypatch)
    monkeypatch.setattr(
        runtime, "validate_configuration", AsyncMock(side_effect=OSError("unreachable"))
    )
    # Another owner opened the database before this start: it is not this call's to close.
    manager.init("postgresql+asyncpg://user:secret@127.0.0.1:1/unused")

    with pytest.raises(OSError):
        await lifespan_module.start_persistence()

    assert not runtime.enabled
    session = manager.create_session()  # still open
    await session.close()

    # An engine this start opened itself is closed with it.
    await manager.close()
    with pytest.raises(OSError):
        await lifespan_module.start_persistence()
    with pytest.raises(Exception, match="not initialized"):
        manager.create_session()


@pytest.mark.asyncio
async def test_a_later_startup_failure_closes_only_the_database_it_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, runtime = _own_singletons(monkeypatch)
    monkeypatch.setattr(lifespan_module.redis_clients, "start", MagicMock())
    monkeypatch.setattr(lifespan_module.redis_clients, "stop", AsyncMock())
    monkeypatch.setattr(lifespan_module.aiohttp_client, "start", MagicMock())
    monkeypatch.setattr(lifespan_module.aiohttp_client, "stop", AsyncMock())
    monkeypatch.setattr(
        lifespan_module.job_manager,
        "init",
        AsyncMock(side_effect=ConnectionError("Redis is unreachable")),
    )
    # Another owner opened the database before this startup: it is not this
    # call's to close.
    manager.init("postgresql+asyncpg://user:secret@127.0.0.1:1/unused")

    with pytest.raises(ConnectionError):
        await lifespan_module.startup()

    assert not runtime.enabled
    session = manager.create_session()  # still open
    await session.close()

    # An engine this startup opened itself is closed with it.
    await manager.close()
    with pytest.raises(ConnectionError):
        await lifespan_module.startup()
    with pytest.raises(Exception, match="not initialized"):
        manager.create_session()
