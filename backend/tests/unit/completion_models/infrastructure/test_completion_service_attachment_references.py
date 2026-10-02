"""Minting of signed references for URL-only persistent attachments.

``get_response`` receives the ids of attachments marked "open with tool". They
are minted alongside the message files only when tools are advertised (an
enabled MCP server and a tool-capable model), audited once per session, and
handed to the context builder so their text is withheld.
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
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.files.file_models import FileType
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer


class _RecordingContextBuilder:
    def __init__(self):
        self.kwargs: dict = {}

    def build_context(self, **kwargs):
        self.kwargs = kwargs
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


def _model(*, supports_tool_calling: bool = True) -> CompletionModel:
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
        supports_tool_calling=supports_tool_calling,
        is_org_enabled=True,
        is_org_default=False,
        tenant_id=uuid4(),
        provider_id=uuid4(),
    )


def _server() -> MCPServer:
    return MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Tables",
        http_url="https://tables.example",
        is_enabled=True,
    )


def _attachment():
    return SimpleNamespace(
        id=uuid4(),
        name="kontoplan.xlsx",
        file_type=FileType.TEXT,
        original_available=True,
        parent_file_id=None,
        text="",
    )


def _service(model: CompletionModel):
    builder = _RecordingContextBuilder()
    service = CompletionService(
        context_builder=builder,
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
        redis_client=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=_DummyAdapter(model))  # type: ignore[method-assign]
    minted: dict = {}

    def fake_mint(files):
        minted["files"] = list(files)
        return {file.id: f"https://x/{file.id}" for file in files}

    service._build_file_reference_urls = fake_mint  # type: ignore[method-assign]
    service._audit_file_reference_mints = AsyncMock()  # type: ignore[method-assign]
    proxy = MagicMock()
    proxy.get_tool_count.return_value = 1
    proxy.get_tools_for_llm.return_value = []
    proxy.prepare_tools_for_context = AsyncMock()
    proxy.close = AsyncMock()
    factory = MagicMock()
    factory.create.return_value = proxy
    service._mcp_proxy_factory = factory  # type: ignore[assignment]
    return service, builder, minted


def _session(*, prior_turns: int = 0):
    return SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        assistant=SimpleNamespace(id=uuid4()),
        questions=[
            SimpleNamespace(files=[], generated_files=[]) for _ in range(prior_turns)
        ],
    )


async def _run(service, model, **kwargs):
    response = await service.get_response(
        model=model, text_input="hi", stream=True, **kwargs
    )
    _ = [chunk async for chunk in response.completion]


@pytest.mark.asyncio
async def test_url_only_attachment_is_minted_and_withheld_when_tools_present():
    model = _model()
    service, builder, minted = _service(model)
    kontoplan, guide = _attachment(), _attachment()

    await _run(
        service,
        model,
        session=_session(),
        prompt_files=[kontoplan, guide],
        url_only_prompt_file_ids={kontoplan.id},
        mcp_servers=[_server()],
    )

    assert minted["files"] == [kontoplan]
    assert builder.kwargs["url_only_prompt_file_ids"] == {kontoplan.id}
    assert builder.kwargs["prompt_files"] == [kontoplan, guide]


@pytest.mark.asyncio
async def test_without_tools_the_attachment_inlines_like_any_other():
    model = _model()
    service, builder, minted = _service(model)
    kontoplan = _attachment()

    await _run(
        service,
        model,
        session=_session(),
        prompt_files=[kontoplan],
        url_only_prompt_file_ids={kontoplan.id},
        mcp_servers=[],
    )

    assert minted["files"] == []
    assert builder.kwargs["url_only_prompt_file_ids"] == set()


@pytest.mark.asyncio
async def test_attachment_mint_is_audited_on_the_first_turn_only():
    model = _model()
    kontoplan = _attachment()

    service, _, _ = _service(model)
    await _run(
        service,
        model,
        session=_session(prior_turns=0),
        prompt_files=[kontoplan],
        url_only_prompt_file_ids={kontoplan.id},
        mcp_servers=[_server()],
    )
    first_turn_audited = service._audit_file_reference_mints.await_args.kwargs["files"]

    service, _, _ = _service(model)
    await _run(
        service,
        model,
        session=_session(prior_turns=1),
        prompt_files=[kontoplan],
        url_only_prompt_file_ids={kontoplan.id},
        mcp_servers=[_server()],
    )
    later_turn_audited = service._audit_file_reference_mints.await_args.kwargs["files"]

    assert kontoplan in first_turn_audited
    assert kontoplan not in later_turn_audited
