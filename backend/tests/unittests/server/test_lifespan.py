from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import eneo.server.dependencies.lifespan as lifespan_module
from eneo.object_content.content import ObjectContentConfigurationError
from eneo.object_content.object_store_connection import (
    ObjectStoreConnectionDatabaseUnavailable,
)


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


@pytest.mark.asyncio
async def test_a_refused_object_store_is_logged_with_its_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The API server reports only that its worker failed to boot, so the
    reason must be in the application's own log before startup fails."""
    settings = SimpleNamespace(
        openapi_only_mode=False,
        database_url="postgresql+asyncpg://unused",
        testing=True,
        encryption_key="unused",
    )
    reason = "Object content storage bucket 'eneo-content' has versioning enabled"
    monkeypatch.setattr(lifespan_module, "get_settings", lambda: settings)
    monkeypatch.setattr(lifespan_module.sessionmanager, "init", MagicMock())
    monkeypatch.setattr(lifespan_module.sessionmanager, "close", AsyncMock())
    monkeypatch.setattr(lifespan_module.object_content_runtime, "start", MagicMock())
    monkeypatch.setattr(
        lifespan_module.object_content_runtime,
        "validate_configuration",
        AsyncMock(side_effect=ObjectContentConfigurationError(reason)),
    )
    monkeypatch.setattr(lifespan_module.object_content_runtime, "stop", AsyncMock())
    monkeypatch.setattr(lifespan_module.aiohttp_client, "start", MagicMock())
    monkeypatch.setattr(lifespan_module.aiohttp_client, "stop", AsyncMock())

    logger = MagicMock()
    monkeypatch.setattr(lifespan_module, "logger", logger)

    with pytest.raises(ObjectContentConfigurationError):
        await lifespan_module.startup()

    [(message, error)] = [call.args for call in logger.error.call_args_list]
    assert reason in message % error


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
