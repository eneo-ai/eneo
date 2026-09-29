import asyncio
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
    monkeypatch.setattr(lifespan_module.aiohttp_client, "start", MagicMock())
    monkeypatch.setattr(lifespan_module.aiohttp_client, "stop", AsyncMock())
    monkeypatch.setattr(lifespan_module.job_manager, "init", AsyncMock())
    monkeypatch.setattr(lifespan_module, "init_predefined_roles", AsyncMock())

    await lifespan_module.startup()

    lifespan_module.object_content_runtime.stop.assert_not_awaited()
    lifespan_module.sessionmanager.close.assert_not_awaited()
    lifespan_module.aiohttp_client.stop.assert_not_awaited()
    lifespan_module.job_manager.init.assert_awaited_once()


def _patch_startup_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    order: list[str],
    *,
    validation_error: BaseException | None = None,
    start_error: BaseException | None = None,
    store_stop_error: BaseException | None = None,
) -> None:
    settings = SimpleNamespace(
        openapi_only_mode=False,
        database_url="postgresql+asyncpg://unused",
        testing=True,
        encryption_key="unused",
    )

    def record(name: str, *, error: BaseException | None = None) -> AsyncMock:
        async def call(*_: object, **__: object) -> None:
            order.append(name)
            if error is not None:
                raise error

        return AsyncMock(side_effect=call)

    def record_sync(name: str, *, error: BaseException | None = None) -> MagicMock:
        def call(*_: object, **__: object) -> None:
            order.append(name)
            if error is not None:
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
        lifespan_module.object_content_runtime,
        "start",
        record_sync("runtime.start", error=start_error),
    )
    monkeypatch.setattr(
        lifespan_module.object_content_runtime,
        "validate_configuration",
        record("runtime.validate", error=validation_error),
    )
    monkeypatch.setattr(
        lifespan_module.object_content_runtime,
        "stop",
        record("runtime.stop", error=store_stop_error),
    )
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

    assert order == [
        "sessionmanager.init",
        "runtime.start",
        "runtime.validate",
        "aiohttp.start",
        "jobs.init",
        "roles",
        "runtime.stop",
        "sessionmanager.close",
        "aiohttp.stop",
        "jobs.close",
        "websockets.shutdown",
    ]


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
