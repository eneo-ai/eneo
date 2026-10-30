from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import anyio
import pytest

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModel,
    Context,
    GeneratedFile,
    ModelKwargs,
    ResponseType,
    ToolCallMetadata,
)
from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.completion_service import (
    CompletionService,
    _name_app_views,
)
from eneo.completion_models.infrastructure.context_builder import ContextBuilder
from eneo.main import stream_lifecycle


class _DummyContextBuilder:
    def build_context(self, **kwargs):
        return Context(input=kwargs.get("input_str", ""), token_count=0)


class _DummyAdapter:
    def __init__(self, model: CompletionModel):
        self.model = model
        self.litellm_model = "dummy/model"
        self.response_model_kwargs: list[ModelKwargs | None] = []
        self.streaming_model_kwargs: list[ModelKwargs | None] = []

    def get_token_limit_of_model(self) -> int:
        return self.model.token_limit

    def get_model_route(self) -> str:
        return self.litellm_model

    async def get_response(
        self,
        *,
        context: Context,
        model_kwargs: ModelKwargs | None,
        mcp_proxy: object | None,
        skill_runtime: object | None = None,
        provider_call_observer: object | None = None,
        provider_call_reason: str = "initial",
    ) -> Completion:
        self.response_model_kwargs.append(model_kwargs)
        return Completion(response_type=ResponseType.TEXT, text=context.input)

    async def prepare_streaming(
        self,
        *,
        context: Context,
        model_kwargs: ModelKwargs | None,
        mcp_proxy: object | None,
        skill_runtime: object | None = None,
    ):
        self.streaming_model_kwargs.append(model_kwargs)
        return SimpleNamespace(_eneo_context={"has_tools": False})

    async def iterate_stream(self, **kwargs):
        pending_approval_ids = kwargs.get("pending_approval_ids")
        assert pending_approval_ids is not None
        pending_approval_ids.add("approval-123")
        yield Completion(response_type=ResponseType.TEXT, text="hello")


def _make_completion_model(
    *,
    supported_model_kwargs: SupportedModelKwargs | None = None,
) -> CompletionModel:
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
        model_kwargs_capabilities=supported_model_kwargs,
    )


@pytest.mark.asyncio
async def test_non_streaming_omits_optional_kwargs_when_capabilities_are_missing():
    completion_model = _make_completion_model()
    adapter = _DummyAdapter(model=completion_model)
    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
    )
    adapter_loader = AsyncMock(return_value=adapter)
    service._get_adapter = adapter_loader

    await service.get_response(
        model=completion_model,
        text_input="hi",
        model_kwargs=ModelKwargs(temperature=0.4, top_p=0.7),
    )

    adapter_loader.assert_awaited_once_with(completion_model)
    assert len(adapter.response_model_kwargs) == 1
    effective_kwargs = adapter.response_model_kwargs[0]
    assert effective_kwargs is not None
    assert effective_kwargs.model_dump(exclude_none=True) == {}


@pytest.mark.asyncio
async def test_model_route_infers_reasoning_choices_from_litellm_when_admin_metadata_is_missing():
    completion_model = _make_completion_model()
    completion_model.reasoning = True
    adapter = MagicMock()
    adapter.provider_type = "openai"
    adapter.resolve_litellm_params.return_value = ("openai/gpt-5.6-terra", {})
    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=adapter)

    with patch(
        "eneo.completion_models.infrastructure.tenant_model_capabilities.resolve_reasoning_effort_options",
        return_value=("low", "medium", "high", "xhigh"),
    ) as resolve_options:
        route = await service.resolve_model_route(completion_model)

    capability = route.supported_model_kwargs.reasoning_effort
    assert capability.supported is True
    assert capability.control == "select"
    assert capability.options == ["low", "medium", "high", "xhigh"]
    resolve_options.assert_called_once_with(
        litellm_model="openai/gpt-5.6-terra",
        provider_type="openai",
    )


def _stored_completion_model(capabilities: object) -> CompletionModel:
    """A reasoning model loaded from its row, capability JSON as stored."""
    loaded = _make_completion_model().model_dump(
        exclude={"supported_model_kwargs", "token_limit", "model_kwargs_capabilities"}
    )
    return CompletionModel.model_validate(
        SimpleNamespace(
            **{**loaded, "reasoning": True},
            model_kwargs_capabilities=capabilities,
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored", "expected_options"),
    [
        # Untagged (develop, or before the squashed tagging migration): the
        # stored record decides, as a discovered snapshot does.
        (
            {
                "reasoning_effort": {
                    "supported": True,
                    "control": "select",
                    "options": ["low", "medium", "high"],
                }
            },
            ["low", "medium", "high"],
        ),
        # Malformed or invalid: fails closed, never widened by discovery.
        (
            {
                "_evidence": "not-a-tag",
                "reasoning_effort": {"supported": True, "options": ["high"]},
            },
            None,
        ),
        ({"reasoning_effort": {"supported": "invalid"}}, None),
    ],
    ids=["untagged", "malformed-tag", "invalid"],
)
async def test_model_route_reads_a_stored_snapshot_without_rediscovering_it(
    stored: object, expected_options: list[str] | None
):
    completion_model = _stored_completion_model(stored)
    adapter = MagicMock()
    adapter.provider_type = "openai"
    adapter.resolve_litellm_params.return_value = ("openai/gpt-5-mini", {})
    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=adapter)

    with patch(
        "eneo.completion_models.infrastructure.tenant_model_capabilities.resolve_reasoning_effort_options",
        return_value=("minimal", "low", "medium", "high", "xhigh"),
    ) as resolve_options:
        route = await service.resolve_model_route(completion_model)

    capability = route.supported_model_kwargs.reasoning_effort
    assert capability.supported is (expected_options is not None)
    assert capability.options == expected_options
    resolve_options.assert_not_called()


@pytest.mark.asyncio
async def test_model_route_preserves_explicit_admin_reasoning_capability():
    completion_model = _make_completion_model(
        supported_model_kwargs=SupportedModelKwargs(
            reasoning_effort=ModelKwargCapability(
                supported=True,
                control="select",
                options=["high"],
            )
        )
    )
    completion_model.reasoning = True
    adapter = MagicMock()
    adapter.provider_type = "openai"
    adapter.resolve_litellm_params.return_value = ("openai/custom-model", {})
    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=adapter)

    with patch(
        "eneo.completion_models.infrastructure.tenant_model_capabilities.resolve_reasoning_effort_options"
    ) as resolve_options:
        route = await service.resolve_model_route(completion_model)

    assert route.supported_model_kwargs.reasoning_effort.options == ["high"]
    resolve_options.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("reasoning", [True, False])
async def test_a_reasoning_row_may_think_without_effort_metadata(reasoning: bool):
    # Mutant: route resolution drops the row's reasoning flag, so a reasoning
    # model on a deployment LiteLLM does not know waits only the silence
    # deadline for its first output.
    completion_model = _make_completion_model(
        supported_model_kwargs=SupportedModelKwargs()
    )
    completion_model.reasoning = reasoning
    adapter = MagicMock()
    adapter.provider_type = "azure"
    adapter.resolve_litellm_params.return_value = ("azure/our-deployment", {})
    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=adapter)

    with (
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.resolve_reasoning_effort_options",
            return_value=(),
        ),
        patch(
            "eneo.completion_models.infrastructure.completion_service.route_takes_reasoning_effort",
            return_value=False,
        ),
    ):
        route = await service.resolve_model_route(completion_model)
        may_reason = route.may_reason_by_default()

    assert route.supported_model_kwargs.reasoning_effort.supported is False
    assert may_reason is reasoning


@pytest.mark.asyncio
@pytest.mark.parametrize("supports_strict_tool_schema", [True, False])
async def test_model_route_carries_the_supports_strict_tool_schema_capability(
    supports_strict_tool_schema: bool,
):
    completion_model = _make_completion_model()
    completion_model.supports_strict_tool_schema = supports_strict_tool_schema
    adapter = MagicMock()
    adapter.provider_type = "openai"
    adapter.resolve_litellm_params.return_value = ("openai/custom-model", {})
    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=adapter)

    route = await service.resolve_model_route(completion_model)

    assert route.supports_strict_tool_schema is supports_strict_tool_schema


@pytest.mark.asyncio
async def test_model_route_drops_strict_schemas_without_tool_calling():
    completion_model = _make_completion_model()
    completion_model.supports_strict_tool_schema = True
    completion_model.supports_tool_calling = False
    adapter = MagicMock()
    adapter.provider_type = "openai"
    adapter.resolve_litellm_params.return_value = ("openai/custom-model", {})
    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=adapter)

    route = await service.resolve_model_route(completion_model)

    assert route.supports_strict_tool_schema is False


@pytest.mark.asyncio
async def test_model_route_without_measured_capability_is_not_strict_capable():
    completion_model = _make_completion_model()
    adapter = MagicMock()
    adapter.provider_type = "openai"
    adapter.resolve_litellm_params.return_value = ("openai/gpt-5.6-luna", {})
    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=adapter)

    route = await service.resolve_model_route(completion_model)

    assert route.supports_strict_tool_schema is False


@pytest.mark.asyncio
async def test_non_streaming_keeps_temperature_for_a_legacy_untagged_slider():
    completion_model = _make_completion_model()
    completion_model.reasoning = True
    object.__setattr__(
        completion_model,
        "model_kwargs_capabilities",
        {
            "temperature": {
                "supported": True,
                "control": "slider",
                "minimum": 0,
                "maximum": 2,
                "step": 0.01,
            }
        },
    )
    adapter = _DummyAdapter(model=completion_model)
    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=adapter)

    await service.get_response(
        model=completion_model,
        text_input="hi",
        model_kwargs=ModelKwargs(temperature=0.0),
    )

    assert len(adapter.response_model_kwargs) == 1
    effective_kwargs = adapter.response_model_kwargs[0]
    assert effective_kwargs is not None
    # Read as a legacy discovered snapshot, as develop reads it.
    assert effective_kwargs.model_dump(exclude_none=True) == {"temperature": 0.0}


@pytest.mark.asyncio
async def test_non_streaming_preserves_supported_kwargs_and_response_format():
    completion_model = _make_completion_model(
        supported_model_kwargs=SupportedModelKwargs(
            temperature=ModelKwargCapability(supported=True, control="slider")
        )
    )
    adapter = _DummyAdapter(model=completion_model)
    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=adapter)
    response_format = {"type": "json_object"}

    await service.get_response(
        model=completion_model,
        text_input="hi",
        model_kwargs=ModelKwargs(
            temperature=0.33,
            top_p=0.8,
            response_format=response_format,
        ),
    )

    assert len(adapter.response_model_kwargs) == 1
    effective_kwargs = adapter.response_model_kwargs[0]
    assert effective_kwargs is not None
    assert effective_kwargs.model_dump(exclude_none=True) == {
        "temperature": 0.33,
        "response_format": response_format,
    }


@pytest.mark.asyncio
async def test_streaming_omits_kwargs_for_invalid_capability_evidence():
    completion_model = _make_completion_model()
    object.__setattr__(
        completion_model,
        "model_kwargs_capabilities",
        {"temperature": {"supported": "invalid"}},
    )
    adapter = _DummyAdapter(model=completion_model)
    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
    )
    adapter_loader = AsyncMock(return_value=adapter)
    service._get_adapter = adapter_loader
    response_format = {"type": "json_object"}

    await service.get_response(
        model=completion_model,
        text_input="hi",
        model_kwargs=ModelKwargs(
            temperature=0.4,
            top_p=0.7,
            response_format=response_format,
        ),
        stream=True,
    )

    adapter_loader.assert_awaited_once_with(completion_model)
    assert len(adapter.streaming_model_kwargs) == 1
    effective_kwargs = adapter.streaming_model_kwargs[0]
    assert effective_kwargs is not None
    assert effective_kwargs.model_dump(exclude_none=True) == {
        "response_format": response_format
    }


@pytest.mark.asyncio
async def test_streaming_preserves_supported_optional_kwargs():
    completion_model = _make_completion_model(
        supported_model_kwargs=SupportedModelKwargs(
            temperature=ModelKwargCapability(supported=True, control="slider")
        )
    )
    adapter = _DummyAdapter(model=completion_model)
    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=adapter)

    await service.get_response(
        model=completion_model,
        text_input="hi",
        model_kwargs=ModelKwargs(temperature=0.61),
        stream=True,
    )

    assert len(adapter.streaming_model_kwargs) == 1
    effective_kwargs = adapter.streaming_model_kwargs[0]
    assert effective_kwargs is not None
    assert effective_kwargs.model_dump(exclude_none=True) == {"temperature": 0.61}


@pytest.mark.asyncio
async def test_streaming_wrapper_cancels_pending_approval_ids():
    completion_model = _make_completion_model()
    adapter = _DummyAdapter(model=completion_model)

    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
        redis_client=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=adapter)

    conversation_session = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        assistant=SimpleNamespace(id=uuid4()),
        questions=[],
    )

    approval_manager = AsyncMock()
    approval_manager.cancel_approval = AsyncMock(return_value=True)

    with patch(
        "eneo.completion_models.infrastructure.completion_service.get_approval_manager",
        return_value=approval_manager,
    ):
        response = await service.get_response(
            model=completion_model,
            text_input="hi",
            session=conversation_session,
            stream=True,
            require_tool_approval=True,
        )
        chunks = [chunk async for chunk in response.completion]

    assert chunks
    assert chunks[0].response_type == ResponseType.TEXT
    assert chunks[0].text == "hello"
    approval_manager.cancel_approval.assert_awaited_once_with("approval-123")


@pytest.mark.asyncio
async def test_estimated_context_overflow_is_still_sent_to_provider():
    completion_model = _make_completion_model()
    completion_model.max_input_tokens = 1
    adapter = _DummyAdapter(model=completion_model)
    adapter.prepare_streaming = AsyncMock(
        return_value=SimpleNamespace(_eneo_context={"has_tools": False})
    )

    service = CompletionService(
        context_builder=ContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
        redis_client=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=adapter)

    response = await service.get_response(
        model=completion_model,
        text_input="This request is intentionally longer than one token.",
        stream=True,
    )

    assert response.total_token_count > completion_model.token_limit
    adapter.prepare_streaming.assert_awaited_once()
    assert (
        adapter.prepare_streaming.await_args.kwargs["context"].token_count
        == response.total_token_count
    )


@pytest.mark.asyncio
async def test_non_streaming_uses_adapter_cumulative_input_estimate():
    completion_model = _make_completion_model()
    adapter = _DummyAdapter(model=completion_model)
    adapter.get_response = AsyncMock(
        return_value=Completion(
            text="ok",
            input_token_estimate=321,
        )
    )

    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
        redis_client=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=adapter)

    response = await service.get_response(
        model=completion_model,
        text_input="hi",
    )

    assert response.total_token_count == 321


async def test_generated_image_chunks_pass_through_tool_call_handling():
    """MCP image blocks reach the ask path as FILES chunks, in stream order."""
    completion_model = _make_completion_model()
    image = GeneratedFile(data=b"\x89PNG", mime_type="image/png")

    class _ImageAdapter(_DummyAdapter):
        async def iterate_stream(self, **kwargs):
            yield Completion(response_type=ResponseType.FILES, image=image)
            yield Completion(
                response_type=ResponseType.TOOL_CALL, tool_calls_metadata=[]
            )
            yield Completion(response_type=ResponseType.TEXT, text="done")

    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
        redis_client=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=_ImageAdapter(model=completion_model))

    response = await service.get_response(
        model=completion_model,
        text_input="draw a cat",
        session=SimpleNamespace(
            id=uuid4(),
            user_id=uuid4(),
            assistant=SimpleNamespace(id=uuid4()),
            questions=[],
        ),
        stream=True,
    )
    chunks = [chunk async for chunk in response.completion]

    assert [chunk.response_type for chunk in chunks] == [
        ResponseType.FILES,
        ResponseType.TOOL_CALL,
        ResponseType.TEXT,
    ]
    assert chunks[0].image is image


async def test_adapter_events_without_text_reach_the_caller():
    """Typed adapter events pass through whether or not they carry text; an
    approval timeout must reach the chat so the pending approval resolves."""
    completion_model = _make_completion_model()
    tools = [
        ToolCallMetadata(server_name="files", tool_name="read", tool_call_id="call-1")
    ]

    class _ApprovalAdapter(_DummyAdapter):
        async def iterate_stream(self, **kwargs):
            yield Completion(
                response_type=ResponseType.TOOL_APPROVAL_REQUIRED,
                approval_id="approval-1",
                tool_calls_metadata=tools,
            )
            yield Completion(
                response_type=ResponseType.TOOL_APPROVAL_TIMEOUT,
                approval_id="approval-1",
                tool_calls_metadata=tools,
            )
            yield Completion(
                response_type=ResponseType.TOOL_CALL, tool_calls_metadata=tools
            )
            yield Completion(text="Okej.")
            yield Completion()
            yield Completion(text="", stop=True)

    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
        redis_client=AsyncMock(),
    )
    service._get_adapter = AsyncMock(
        return_value=_ApprovalAdapter(model=completion_model)
    )

    response = await service.get_response(
        model=completion_model,
        text_input="read a.txt",
        session=SimpleNamespace(
            id=uuid4(),
            user_id=uuid4(),
            assistant=SimpleNamespace(id=uuid4()),
            questions=[],
        ),
        stream=True,
    )
    chunks = [chunk async for chunk in response.completion]

    # The empty untyped chunk carries nothing and is the only one dropped.
    assert [(chunk.response_type, chunk.stop) for chunk in chunks] == [
        (ResponseType.TOOL_APPROVAL_REQUIRED, False),
        (ResponseType.TOOL_APPROVAL_TIMEOUT, False),
        (ResponseType.TOOL_CALL, False),
        (ResponseType.TEXT, False),
        (None, True),
    ]


class _ViewProxy:
    """Proxy whose ``weather__get_weather`` tool has an approved view."""

    def __init__(self, *, fails: bool = False):
        self.fails = fails
        self.view = SimpleNamespace(
            view_id=uuid4(), mcp_server_id=uuid4(), ui_meta={"prefersBorder": True}
        )

    async def approved_app_view(self, prefixed_tool_name: str):
        if self.fails:
            raise RuntimeError("database unavailable")
        return self.view if prefixed_tool_name == "weather__get_weather" else None


def _tool_call_chunk(**call) -> Completion:
    return Completion(
        response_type=ResponseType.TOOL_CALL,
        tool_calls_metadata=[
            ToolCallMetadata(server_name="weather", tool_name="get_weather", **call)
        ],
    )


async def test_view_is_named_on_a_call_from_the_moment_it_is_announced():
    proxy = _ViewProxy()
    pending = _tool_call_chunk(
        mcp_tool_name="weather__get_weather", result_status="pending"
    )

    await _name_app_views(pending, proxy)

    assert pending.tool_calls_metadata[0].app_view == {
        "view_id": str(proxy.view.view_id),
        "mcp_server_id": str(proxy.view.mcp_server_id),
        "ui": {"prefersBorder": True},
    }


async def test_call_of_a_tool_without_a_view_is_left_as_it_is():
    chunk = _tool_call_chunk(mcp_tool_name="weather__get_forecast")

    await _name_app_views(chunk, _ViewProxy())

    assert chunk.tool_calls_metadata[0].app_view is None


async def test_failed_view_lookup_never_breaks_the_answer():
    chunk = _tool_call_chunk(mcp_tool_name="weather__get_weather")

    await _name_app_views(chunk, _ViewProxy(fails=True))

    assert chunk.tool_calls_metadata[0].app_view is None


async def test_proxy_that_knows_no_views_is_harmless():
    chunk = _tool_call_chunk(mcp_tool_name="weather__get_weather")

    await _name_app_views(chunk, object())
    await _name_app_views(chunk, None)

    assert chunk.tool_calls_metadata[0].app_view is None


def _conversation_session() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        assistant=SimpleNamespace(id=uuid4()),
        questions=[],
    )


def _service(adapter: object) -> CompletionService:
    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
        redis_client=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=adapter)
    return service


@pytest.mark.asyncio
async def test_closing_the_completion_runs_stream_cleanup_on_the_same_task():
    """A client abort closes the typed stream; the wrapper behind it must clean
    up right away, on the consumer's task."""
    completion_model = _make_completion_model()
    service = _service(_DummyAdapter(model=completion_model))

    cancelled_on: list[asyncio.Task[object] | None] = []
    approval_manager = AsyncMock()
    approval_manager.cancel_approval = AsyncMock(
        side_effect=lambda _id: cancelled_on.append(asyncio.current_task())
    )

    with patch(
        "eneo.completion_models.infrastructure.completion_service.get_approval_manager",
        return_value=approval_manager,
    ):
        response = await service.get_response(
            model=completion_model,
            text_input="hi",
            session=_conversation_session(),
            stream=True,
            require_tool_approval=True,
        )
        assert (await anext(response.completion)).text == "hello"
        await response.completion.aclose()

    assert cancelled_on == [asyncio.current_task()]


@pytest.mark.asyncio
async def test_closing_the_completion_closes_the_adapter_stream_at_once():
    """The adapter's generator holds the provider stream; closing the typed
    completion must close it right away, not leave it to the GC."""
    closed_on: list[asyncio.Task[object] | None] = []

    class TrackingAdapter(_DummyAdapter):
        async def iterate_stream(self, **kwargs):
            try:
                async for chunk in super().iterate_stream(**kwargs):
                    yield chunk
                    yield chunk
            finally:
                closed_on.append(asyncio.current_task())

    completion_model = _make_completion_model()
    service = _service(TrackingAdapter(model=completion_model))

    response = await service.get_response(
        model=completion_model, text_input="hi", stream=True
    )
    await anext(response.completion)
    await response.completion.aclose()

    assert closed_on == [asyncio.current_task()]


class _ClosableStream:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeProxy:
    def __init__(self) -> None:
        self.closed = False

    def allow_file_references(self, *args, **kwargs) -> None:
        pass

    def set_document_template(self, reference) -> None:
        pass

    async def prepare_tools_for_context(self) -> None:
        pass

    def get_tool_count(self) -> int:
        return 0

    def get_tools_for_llm(self) -> list[dict[str, object]]:
        return []

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_closing_an_unstarted_completion_releases_what_was_prepared():
    """The provider request and the MCP proxy exist before the response starts.
    A body that never iterates must still release them."""
    prepared = _ClosableStream()
    proxy = _FakeProxy()

    class PreparingAdapter(_DummyAdapter):
        async def prepare_streaming(self, **kwargs):
            return SimpleNamespace(stream=prepared, _eneo_context={"has_tools": False})

    completion_model = _make_completion_model()
    service = _service(PreparingAdapter(model=completion_model))
    service._mcp_proxy_factory = SimpleNamespace(create=lambda *a, **k: proxy)

    response = await service.get_response(
        model=completion_model,
        text_input="hi",
        stream=True,
        mcp_servers=[SimpleNamespace(id=uuid4(), name="server", is_enabled=True)],
    )
    await response.completion.aclose()

    assert prepared.closed
    assert proxy.closed


@pytest.mark.asyncio
async def test_a_failing_prepared_stream_close_still_releases_the_proxy():
    proxy = _FakeProxy()

    class _BrokenStream:
        async def aclose(self) -> None:
            raise RuntimeError("provider close failed")

    class PreparingAdapter(_DummyAdapter):
        async def prepare_streaming(self, **kwargs):
            return SimpleNamespace(
                stream=_BrokenStream(), _eneo_context={"has_tools": False}
            )

    completion_model = _make_completion_model()
    service = _service(PreparingAdapter(model=completion_model))
    service._mcp_proxy_factory = SimpleNamespace(create=lambda *a, **k: proxy)

    response = await service.get_response(
        model=completion_model,
        text_input="hi",
        stream=True,
        mcp_servers=[SimpleNamespace(id=uuid4(), name="server", is_enabled=True)],
    )
    await response.completion.aclose()

    assert proxy.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_externally", [False, True])
async def test_a_shielded_prepared_stream_cannot_delay_the_proxy_cleanup(
    monkeypatch: pytest.MonkeyPatch, cancel_externally: bool
):
    monkeypatch.setattr(stream_lifecycle, "FINALIZATION_BUDGET_SECONDS", 0.02)
    proxy = _FakeProxy()
    cancelled = False
    started = asyncio.Event()

    class ShieldedStream:
        async def aclose(self) -> None:
            nonlocal cancelled
            started.set()
            with anyio.CancelScope(shield=True):
                try:
                    await asyncio.sleep(0.2)
                except asyncio.CancelledError:
                    cancelled = True

    class PreparingAdapter(_DummyAdapter):
        async def prepare_streaming(self, **kwargs):
            return SimpleNamespace(stream=ShieldedStream())

    completion_model = _make_completion_model()
    service = _service(PreparingAdapter(model=completion_model))
    service._mcp_proxy_factory = SimpleNamespace(create=lambda *a, **k: proxy)
    response = await service.get_response(
        model=completion_model,
        text_input="hi",
        stream=True,
        mcp_servers=[SimpleNamespace(id=uuid4(), name="server", is_enabled=True)],
    )
    if cancel_externally:
        closing = asyncio.create_task(response.completion.aclose())
        await started.wait()
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
    else:
        await response.completion.aclose()

    assert cancelled
    assert proxy.closed
