"""Runtime enforcement of org-level MCP server disable (issue #501).

Disabling a server only flips ``MCPServers.is_enabled``; the assistant->server
associations are never pruned, so a disabled server can still be handed to
``CompletionService.get_response``. That method is the single boundary where MCP
servers are connected and their tools exposed, so it must drop disabled servers
before building the proxy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModel,
    Context,
    ResponseType,
)
from intric.completion_models.infrastructure.completion_service import CompletionService
from intric.mcp_servers.domain.entities.mcp_server import MCPServer


class _DummyContextBuilder:
    def build_context(self, **kwargs):
        return Context(input=kwargs.get("input_str", ""), token_count=0)


class _DummyAdapter:
    def __init__(self, model: CompletionModel):
        self.model = model

    def get_token_limit_of_model(self) -> int:
        return self.model.token_limit

    def get_model_route(self) -> str:
        return "dummy/model"

    async def prepare_streaming(self, **kwargs):
        return SimpleNamespace(_eneo_context={"has_tools": False})

    async def iterate_stream(self, **kwargs):
        yield Completion(response_type=ResponseType.TEXT, text="hello")


def _make_completion_model() -> CompletionModel:
    now = datetime.now(timezone.utc)
    return CompletionModel(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="dummy-model",
        nickname="dummy",
        family="openai",
        max_input_tokens=8000,
        max_output_tokens=4000,
        is_deprecated=False,
        stability="stable",
        hosting="eu",
        vision=False,
        reasoning=False,
        supports_tool_calling=True,
        is_org_enabled=True,
        is_org_default=False,
        tenant_id=uuid4(),
        provider_id=uuid4(),
    )


def _mcp_server(*, name: str, is_enabled: bool) -> MCPServer:
    return MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name=name,
        http_url=f"https://{name.lower()}.example",
        is_enabled=is_enabled,
    )


def _service_with_mocked_proxy() -> tuple[CompletionService, MagicMock]:
    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
        redis_client=AsyncMock(),
    )
    service._get_adapter = AsyncMock(  # type: ignore[method-assign]
        return_value=_DummyAdapter(model=_make_completion_model())
    )

    mock_proxy = MagicMock()
    mock_proxy.get_tool_count.return_value = 1
    mock_proxy.get_tools_for_llm.return_value = []
    mock_proxy.close = AsyncMock()

    factory = MagicMock()
    factory.create.return_value = mock_proxy
    service._mcp_proxy_factory = factory  # type: ignore[assignment]
    return service, factory


def _session() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        assistant=SimpleNamespace(id=uuid4()),
    )


@pytest.mark.asyncio
async def test_disabled_mcp_server_is_filtered_before_proxy_is_built():
    service, factory = _service_with_mocked_proxy()
    model = _make_completion_model()
    enabled = _mcp_server(name="Enabled", is_enabled=True)
    disabled = _mcp_server(name="Disabled", is_enabled=False)

    response = await service.get_response(
        model=model,
        text_input="hi",
        session=_session(),
        stream=True,
        mcp_servers=[enabled, disabled],
    )
    # Drain the stream so the proxy cleanup path runs.
    _ = [chunk async for chunk in response.completion]

    factory.create.assert_called_once()
    servers_arg = factory.create.call_args.args[0]
    assert servers_arg == [enabled]
    assert all(server.is_enabled for server in servers_arg)


@pytest.mark.asyncio
async def test_all_disabled_mcp_servers_build_no_proxy():
    service, factory = _service_with_mocked_proxy()
    model = _make_completion_model()
    disabled = _mcp_server(name="Disabled", is_enabled=False)

    response = await service.get_response(
        model=model,
        text_input="hi",
        session=_session(),
        stream=True,
        mcp_servers=[disabled],
    )
    _ = [chunk async for chunk in response.completion]

    factory.create.assert_not_called()
