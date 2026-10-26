from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import eneo.server.dependencies.lifespan as lifespan_module
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
async def test_shutdown_drains_streamed_turns_before_closing_their_pools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(openapi_only_mode=False)
    monkeypatch.setattr(lifespan_module, "get_settings", lambda: settings)
    order: list[str] = []

    def step(name: str) -> AsyncMock:
        return AsyncMock(side_effect=lambda *a, **k: order.append(name))

    monkeypatch.setattr(lifespan_module, "drain_background_saves", step("saves"))
    monkeypatch.setattr(lifespan_module, "drain_connection_hosts", step("mcp"))
    monkeypatch.setattr(lifespan_module.object_content_runtime, "stop", step("objects"))
    monkeypatch.setattr(lifespan_module.sessionmanager, "close", step("db"))
    monkeypatch.setattr(lifespan_module.aiohttp_client, "stop", step("http"))
    monkeypatch.setattr(lifespan_module.job_manager, "close", step("jobs"))
    monkeypatch.setattr(lifespan_module.websocket_manager, "shutdown", step("ws"))

    await lifespan_module.shutdown()

    assert order.index("saves") < order.index("db")
    assert order.index("mcp") < order.index("db")
    assert order.index("mcp") < order.index("http")
