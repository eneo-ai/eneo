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

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModel,
    Context,
    ResponseType,
)
from eneo.completion_models.domain.skill_activation import (
    FrozenSkillInstruction,
    SkillActivationRuntime,
)
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.completion_models.infrastructure.context_builder import ContextBuilder
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
from eneo.mcp_servers.domain.model_tool_identity import ModelToolIdentity
from eneo.skills.domain.skill import ResolvedSkillBinding, SkillBindingSource


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
    mock_proxy.prepare_tools_for_context = AsyncMock()
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
        questions=[],
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
    factory.create.return_value.prepare_tools_for_context.assert_awaited_once_with()


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


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_skill_reference_uses_prepared_tools_without_enabling_its_server(enabled):
    service, factory = _service_with_mocked_proxy()
    service.context_builder = ContextBuilder()
    adapter = service._get_adapter.return_value
    adapter.prepare_streaming = AsyncMock(
        return_value=SimpleNamespace(_eneo_context={"has_tools": enabled})
    )
    server = _mcp_server(name="Time", is_enabled=enabled)
    binding = ResolvedSkillBinding(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        current_revision_id=uuid4(),
        skill_space_id=uuid4(),
        slug="communication",
        revision_number=1,
        current_revision_number=1,
        display_name="Communication",
        instructions=f"Write clearly. Use [Time](eneo-tool:{server.id}/today).",
        content_digest="a" * 64,
        position=0,
        source=SkillBindingSource.SPACE,
    )
    runtime = SkillActivationRuntime.create(
        base_instructions="Base",
        skills=(FrozenSkillInstruction("skill-1", binding, True),),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=10,
        context_share_percent=10,
        model_route="openai/gpt-4o",
        max_input_tokens=128_000,
        supports_tool_calling=True,
    )
    identity = ModelToolIdentity("renamed_time__today", server.id, "today", "general")
    proxy = factory.create.return_value

    def prepared_identities():
        proxy.prepare_tools_for_context.assert_awaited_once()
        return (identity,)

    proxy.get_model_tool_identities.side_effect = prepared_identities
    response = await service.get_response(
        model=_make_completion_model(),
        text_input="Write an update",
        prompt=runtime.prompt + "\nAttachment context",
        skill_runtime=runtime,
        session=_session(),
        stream=True,
        mcp_servers=[server],
    )
    _ = [chunk async for chunk in response.completion]

    context = adapter.prepare_streaming.await_args.kwargs["context"]
    assert "Write clearly." in context.prompt
    assert "Attachment context" in context.prompt
    assert runtime.snapshot().references_prepared
    assert runtime.snapshot().reference_tools == ((identity,) if enabled else ())
    if enabled:
        assert f"MCP {server.id}, tool today; available" in context.prompt
        proxy.include_reference_identities.assert_called_once()
        proxy.close.assert_awaited_once()
    else:
        assert (
            f"MCP {server.id}, tool today; unavailable for this turn" in context.prompt
        )
        factory.create.assert_not_called()
