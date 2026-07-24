from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import ResponseType
from eneo.completion_models.domain.skill_activation import (
    SKILL_ACTIVATION_TOOL_NAME,
    FrozenSkillInstruction,
    SkillActivationRejectionReason,
    SkillActivationRuntime,
)
from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    PreparedModelStream,
    TenantModelAdapter,
)
from eneo.main.exceptions import OpenAIException
from eneo.skills.domain.skill import ResolvedSkillBinding, SkillBindingSource
from eneo.tokens.token_utils import measure_provider_input_tokens


class _AsyncChunkStream:
    def __init__(self, chunks: list[object]) -> None:
        self._chunks = chunks

    def __aiter__(self):
        self._iterator = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration


class _FakeMCPProxy:
    def __init__(self) -> None:
        self.calls: list[list[tuple[str, dict[str, object]]]] = []

    def get_tools_for_llm(self) -> list[dict[str, object]]:
        return [
            {
                "type": "function",
                "function": {"name": "server__lookup"},
            }
        ]

    def get_allowed_tool_names(self) -> set[str]:
        return {"server__lookup"}

    def get_tool_info(self, name: str) -> tuple[str, str, str | None] | None:
        if name == "server__lookup":
            return ("server", "lookup", "Lookup")
        return None

    async def refresh_tools(self, *, touched_tool_names: list[str]) -> bool:
        del touched_tool_names
        return False

    async def call_tools_parallel(
        self, calls: list[tuple[str, dict[str, object]]]
    ) -> list[dict[str, object]]:
        self.calls.append(calls)
        return [
            {
                "content": [{"type": "text", "text": "lookup result"}],
                "is_error": False,
            }
            for _ in calls
        ]


class _CollisionMCPProxy(_FakeMCPProxy):
    def get_tools_for_llm(self) -> list[dict[str, object]]:
        return [
            {
                "type": "function",
                "function": {"name": SKILL_ACTIVATION_TOOL_NAME},
            }
        ]


def _runtime(*, selective_activation_enabled: bool = True) -> SkillActivationRuntime:
    binding = ResolvedSkillBinding(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        current_revision_id=uuid4(),
        skill_space_id=uuid4(),
        slug="payroll",
        revision_number=2,
        current_revision_number=2,
        display_name="Payroll",
        description="Use for payroll questions",
        instructions="Use the exact payroll procedure.",
        content_digest="a" * 64,
        position=0,
        source=SkillBindingSource.SPACE,
    )
    return SkillActivationRuntime.create(
        base_instructions="Base instructions",
        skills=(
            FrozenSkillInstruction(
                activation_key="skill-1",
                binding=binding,
                initially_active=False,
            ),
        ),
        blocked_keys=frozenset({"blocked-skill-1"}),
        selective_activation_enabled=selective_activation_enabled,
        max_activations_per_turn=2,
        context_share_percent=100,
        model_route="openai/test-model",
        max_input_tokens=128_000,
        supports_tool_calling=True,
    )


def _always_only_runtime() -> SkillActivationRuntime:
    return SkillActivationRuntime.create(
        base_instructions="Base instructions",
        skills=(),
        blocked_keys=frozenset(),
        selective_activation_enabled=True,
        max_activations_per_turn=2,
        context_share_percent=100,
        model_route="openai/test-model",
        max_input_tokens=128_000,
        supports_tool_calling=True,
    )


def _adapter() -> TenantModelAdapter:
    adapter = object.__new__(TenantModelAdapter)
    adapter.litellm_model = "openai/test-model"
    adapter.provider_type = "openai"
    adapter.model = SimpleNamespace(
        name="test-model",
        supports_tool_calling=True,
    )
    adapter._prepare_kwargs = Mock(return_value={})
    adapter._create_messages_from_context = Mock(
        return_value=[
            {
                "role": "system",
                "content": "Base instructions\n\nKNOWLEDGE_SENTINEL",
            },
            {"role": "user", "content": "Help with payroll"},
        ]
    )
    adapter._build_tools_from_context = Mock(return_value=[])
    adapter._merge_mcp_tools = Mock(return_value=[])
    adapter._get_dropped_params = Mock(return_value=set())
    adapter._get_effective_params = Mock(return_value={})
    return adapter


def _provider_tool_call(
    *,
    call_id: str,
    name: str,
    arguments: str,
) -> object:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _response(
    *,
    content: str | None = None,
    tool_calls: list[object] | None = None,
    finish_reason: str = "stop",
) -> object:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    reasoning_content=None,
                    tool_calls=tool_calls,
                ),
                finish_reason=finish_reason,
            )
        ],
        usage=None,
    )


def _tool_chunk(
    *,
    calls: list[tuple[str, str, str]],
    content: str | None = None,
) -> object:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=content,
                    reasoning_content=None,
                    tool_calls=[
                        SimpleNamespace(
                            index=index,
                            id=call_id,
                            function=SimpleNamespace(
                                name=name,
                                arguments=arguments,
                            ),
                        )
                        for index, (call_id, name, arguments) in enumerate(calls)
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=None,
    )


def _text_chunk(text: str) -> object:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=text,
                    reasoning_content=None,
                    tool_calls=None,
                ),
                finish_reason="stop",
            )
        ],
        usage=None,
    )


@pytest.mark.asyncio
async def test_non_streaming_activates_skill_before_follow_up() -> None:
    adapter = _adapter()
    runtime = _runtime()
    responses = [
        _response(
            tool_calls=[
                _provider_tool_call(
                    call_id="activation-1",
                    name=SKILL_ACTIVATION_TOOL_NAME,
                    arguments='{"skill_key":"skill-1"}',
                )
            ],
            finish_reason="tool_calls",
        ),
        _response(content="Payroll answer"),
    ]

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(side_effect=responses),
    ) as completion_call:
        completion = await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            skill_runtime=runtime,
        )

    assert completion.text == "Payroll answer"
    assert runtime.snapshot().accepted == ("skill-1",)
    follow_up_messages = completion_call.await_args_list[1].kwargs["messages"]
    assert follow_up_messages[0]["role"] == "system"
    assert "Use the exact payroll procedure." in follow_up_messages[0]["content"]
    assert "KNOWLEDGE_SENTINEL" in follow_up_messages[0]["content"]


@pytest.mark.asyncio
async def test_non_streaming_rejects_unadvertised_activation_with_mcp_present() -> None:
    adapter = _adapter()
    runtime = _runtime(selective_activation_enabled=False)
    proxy = _CollisionMCPProxy()
    initial_prompt = runtime.prompt
    responses = [
        _response(
            tool_calls=[
                _provider_tool_call(
                    call_id="activation-1",
                    name=SKILL_ACTIVATION_TOOL_NAME,
                    arguments='{"skill_key":"skill-1"}',
                )
            ],
            finish_reason="tool_calls",
        ),
        _response(content="Answer without the hidden Skill"),
    ]

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(side_effect=responses),
    ):
        completion = await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            mcp_proxy=proxy,
            skill_runtime=runtime,
        )

    snapshot = runtime.snapshot()
    assert completion.text == "Answer without the hidden Skill"
    assert runtime.prompt == initial_prompt
    assert snapshot.accepted == ()
    assert snapshot.active == ()
    assert snapshot.rejected[0].reason is (
        SkillActivationRejectionReason.ACTIVATION_UNAVAILABLE
    )
    assert proxy.calls == []


@pytest.mark.asyncio
async def test_non_streaming_estimates_every_request_when_provider_omits_usage() -> (
    None
):
    adapter = _adapter()
    runtime = _runtime()
    responses = [
        _response(
            tool_calls=[
                _provider_tool_call(
                    call_id="activation-1",
                    name=SKILL_ACTIVATION_TOOL_NAME,
                    arguments='{"skill_key":"skill-1"}',
                )
            ],
            finish_reason="tool_calls",
        ),
        _response(content="Payroll answer"),
    ]
    request_payloads: list[tuple[list[dict[str, object]], list[dict[str, object]]]] = []

    async def complete(**kwargs):
        request_payloads.append(
            (
                deepcopy(kwargs["messages"]),
                deepcopy(kwargs.get("tools") or []),
            )
        )
        return responses[len(request_payloads) - 1]

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        complete,
    ):
        completion = await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            skill_runtime=runtime,
        )

    expected = sum(
        measure_provider_input_tokens(messages, tools, adapter.litellm_model).tokens
        for messages, tools in request_payloads
    )
    assert len(request_payloads) == 2
    assert request_payloads[1][0][-2]["role"] == "assistant"
    assert request_payloads[1][0][-1]["role"] == "tool"
    assert completion.input_token_estimate == expected
    assert completion.usage is None or completion.usage.prompt_tokens is None


@pytest.mark.asyncio
async def test_non_streaming_maps_prompt_ownership_failure_without_mutating_runtime() -> (
    None
):
    adapter = _adapter()
    adapter._create_messages_from_context = Mock(
        return_value=[
            {"role": "system", "content": "DIFFERENT_BASE"},
            {"role": "user", "content": "Help with payroll"},
        ]
    )
    runtime = _runtime()
    snapshot_before = runtime.snapshot()

    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
            AsyncMock(
                return_value=_response(
                    tool_calls=[
                        _provider_tool_call(
                            call_id="activation-1",
                            name=SKILL_ACTIVATION_TOOL_NAME,
                            arguments='{"skill_key":"skill-1"}',
                        )
                    ],
                    finish_reason="tool_calls",
                )
            ),
        ),
        pytest.raises(OpenAIException) as exc_info,
    ):
        await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            skill_runtime=runtime,
        )

    assert exc_info.value.code == "skill_prompt_ownership"
    assert runtime.snapshot() == snapshot_before


@pytest.mark.asyncio
async def test_non_streaming_rejects_duplicate_provider_call_ids() -> None:
    adapter = _adapter()
    runtime = _runtime()

    with (
        patch(
            "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
            AsyncMock(
                return_value=_response(
                    tool_calls=[
                        _provider_tool_call(
                            call_id="duplicate",
                            name=SKILL_ACTIVATION_TOOL_NAME,
                            arguments='{"skill_key":"skill-1"}',
                        ),
                        _provider_tool_call(
                            call_id="duplicate",
                            name=SKILL_ACTIVATION_TOOL_NAME,
                            arguments='{"skill_key":"skill-1"}',
                        ),
                    ],
                    finish_reason="tool_calls",
                )
            ),
        ),
        pytest.raises(OpenAIException) as exc_info,
    ):
        await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            skill_runtime=runtime,
        )

    assert exc_info.value.code == "invalid_tool_call"


@pytest.mark.asyncio
async def test_non_streaming_existing_builtin_is_not_treated_as_unauthorized_without_mcp() -> (
    None
):
    adapter = _adapter()
    runtime = _runtime()

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(
            return_value=_response(
                tool_calls=[
                    _provider_tool_call(
                        call_id="image-1",
                        name="generate_image",
                        arguments='{"prompt":"A municipal skyline"}',
                    )
                ],
                finish_reason="tool_calls",
            )
        ),
    ) as completion_call:
        await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            skill_runtime=runtime,
        )

    assert completion_call.await_count == 1


@pytest.mark.asyncio
async def test_accepted_activation_defers_external_sibling_call() -> None:
    adapter = _adapter()
    runtime = _runtime()
    proxy = _FakeMCPProxy()
    responses = [
        _response(
            tool_calls=[
                _provider_tool_call(
                    call_id="activation-1",
                    name=SKILL_ACTIVATION_TOOL_NAME,
                    arguments='{"skill_key":"skill-1"}',
                ),
                _provider_tool_call(
                    call_id="external-1",
                    name="server__lookup",
                    arguments='{"query":"payroll"}',
                ),
            ],
            finish_reason="tool_calls",
        ),
        _response(content="Updated answer"),
    ]

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(side_effect=responses),
    ):
        await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            mcp_proxy=proxy,
            skill_runtime=runtime,
        )

    assert proxy.calls == []


@pytest.mark.asyncio
async def test_rejected_activation_keeps_external_sibling_dispatchable() -> None:
    adapter = _adapter()
    runtime = _runtime()
    proxy = _FakeMCPProxy()
    responses = [
        _response(
            tool_calls=[
                _provider_tool_call(
                    call_id="activation-1",
                    name=SKILL_ACTIVATION_TOOL_NAME,
                    arguments='{"skill_key":"missing"}',
                ),
                _provider_tool_call(
                    call_id="external-1",
                    name="server__lookup",
                    arguments='{"query":"payroll"}',
                ),
            ],
            finish_reason="tool_calls",
        ),
        _response(content="Lookup answer"),
    ]

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(side_effect=responses),
    ):
        await adapter.get_response(
            context=SimpleNamespace(),
            model_kwargs={},
            mcp_proxy=proxy,
            skill_runtime=runtime,
        )

    assert proxy.calls == [[("server__lookup", {"query": "payroll"})]]
    assert runtime.snapshot().rejected[0].reason is (
        SkillActivationRejectionReason.UNKNOWN_KEY
    )


@pytest.mark.asyncio
async def test_streaming_activates_skill_without_mcp_proxy() -> None:
    adapter = _adapter()
    runtime = _runtime()
    prepared = PreparedModelStream(
        stream=_AsyncChunkStream(
            [
                _tool_chunk(
                    calls=[
                        (
                            "activation-1",
                            SKILL_ACTIVATION_TOOL_NAME,
                            '{"skill_key":"skill-1"}',
                        )
                    ],
                    content="I will load the payroll procedure.",
                )
            ]
        ),
        messages=[
            {"role": "system", "content": "Base instructions"},
            {"role": "user", "content": "Help with payroll"},
        ],
        kwargs={"tools": []},
        mcp_proxy=None,
        skill_runtime=runtime,
        has_tools=True,
    )

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(return_value=_AsyncChunkStream([_text_chunk("Payroll answer")])),
    ) as completion_call:
        output = [
            completion
            async for completion in adapter.iterate_stream(
                stream=prepared,
                model_kwargs={},
            )
        ]

    assert any(completion.text == "Payroll answer" for completion in output)
    assert runtime.snapshot().accepted == ("skill-1",)
    follow_up_messages = completion_call.await_args.kwargs["messages"]
    assert "Use the exact payroll procedure." in follow_up_messages[0]["content"]
    assert follow_up_messages[-2]["content"] == ("I will load the payroll procedure.")


@pytest.mark.asyncio
async def test_streaming_rejects_unadvertised_activation_with_mcp_present() -> None:
    adapter = _adapter()
    runtime = _runtime(selective_activation_enabled=False)
    proxy = _CollisionMCPProxy()
    initial_prompt = runtime.prompt
    prepared = PreparedModelStream(
        stream=_AsyncChunkStream(
            [
                _tool_chunk(
                    calls=[
                        (
                            "activation-1",
                            SKILL_ACTIVATION_TOOL_NAME,
                            '{"skill_key":"skill-1"}',
                        )
                    ]
                )
            ]
        ),
        messages=[
            {"role": "system", "content": initial_prompt},
            {"role": "user", "content": "Help with payroll"},
        ],
        kwargs={"tools": proxy.get_tools_for_llm()},
        mcp_proxy=proxy,
        skill_runtime=runtime,
        has_tools=True,
    )

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(
            return_value=_AsyncChunkStream(
                [_text_chunk("Answer without the hidden Skill")]
            )
        ),
    ):
        output = [
            completion
            async for completion in adapter.iterate_stream(
                stream=prepared,
                model_kwargs={},
            )
        ]

    snapshot = runtime.snapshot()
    assert any(
        completion.text == "Answer without the hidden Skill" for completion in output
    )
    assert runtime.prompt == initial_prompt
    assert snapshot.accepted == ()
    assert snapshot.active == ()
    assert snapshot.rejected[0].reason is (
        SkillActivationRejectionReason.ACTIVATION_UNAVAILABLE
    )
    assert proxy.calls == []


@pytest.mark.asyncio
async def test_streaming_estimates_every_request_when_provider_omits_usage() -> None:
    adapter = _adapter()
    runtime = _runtime()
    adapter._merge_mcp_tools = Mock(
        return_value=[
            {
                "type": "function",
                "function": {"name": SKILL_ACTIVATION_TOOL_NAME},
            }
        ]
    )
    streams = [
        _AsyncChunkStream(
            [
                _tool_chunk(
                    calls=[
                        (
                            "activation-1",
                            SKILL_ACTIVATION_TOOL_NAME,
                            '{"skill_key":"skill-1"}',
                        )
                    ]
                )
            ]
        ),
        _AsyncChunkStream([_text_chunk("Payroll answer")]),
    ]
    request_payloads: list[tuple[list[dict[str, object]], list[dict[str, object]]]] = []

    async def complete(**kwargs):
        request_payloads.append(
            (
                deepcopy(kwargs["messages"]),
                deepcopy(kwargs.get("tools") or []),
            )
        )
        return streams[len(request_payloads) - 1]

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        complete,
    ):
        prepared = await adapter.prepare_streaming(
            context=SimpleNamespace(),
            model_kwargs={},
            skill_runtime=runtime,
        )
        output = [
            completion
            async for completion in adapter.iterate_stream(
                stream=prepared,
                model_kwargs={},
            )
        ]

    expected = sum(
        measure_provider_input_tokens(messages, tools, adapter.litellm_model).tokens
        for messages, tools in request_payloads
    )
    assert len(request_payloads) == 2
    assert request_payloads[1][0][-2]["role"] == "assistant"
    assert request_payloads[1][0][-1]["role"] == "tool"
    assert output[-1].input_token_estimate == expected
    assert output[-1].usage is None


@pytest.mark.asyncio
async def test_streaming_accepted_activation_defers_external_sibling_call() -> None:
    adapter = _adapter()
    runtime = _runtime()
    proxy = _FakeMCPProxy()
    prepared = PreparedModelStream(
        stream=_AsyncChunkStream(
            [
                _tool_chunk(
                    calls=[
                        (
                            "activation-1",
                            SKILL_ACTIVATION_TOOL_NAME,
                            '{"skill_key":"skill-1"}',
                        ),
                        (
                            "external-1",
                            "server__lookup",
                            '{"query":"payroll"}',
                        ),
                    ]
                )
            ]
        ),
        messages=[
            {"role": "system", "content": "Base instructions"},
            {"role": "user", "content": "Help with payroll"},
        ],
        kwargs={"tools": []},
        mcp_proxy=proxy,
        skill_runtime=runtime,
        has_tools=True,
    )

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(return_value=_AsyncChunkStream([_text_chunk("Payroll answer")])),
    ):
        output = [
            completion
            async for completion in adapter.iterate_stream(
                stream=prepared,
                model_kwargs={},
            )
        ]

    assert any(completion.text == "Payroll answer" for completion in output)
    assert runtime.snapshot().accepted == ("skill-1",)
    assert proxy.calls == []
    deferred = [
        metadata
        for completion in output
        for metadata in completion.tool_calls_metadata or []
        if metadata.tool_call_id == "external-1"
    ]
    assert deferred
    assert deferred[-1].result_status == "deferred"


@pytest.mark.asyncio
async def test_streaming_existing_builtin_is_not_treated_as_unauthorized_without_mcp() -> (
    None
):
    adapter = _adapter()
    for runtime in (_always_only_runtime(), _runtime()):
        prepared = PreparedModelStream(
            stream=_AsyncChunkStream(
                [
                    _tool_chunk(
                        calls=[
                            (
                                "image-1",
                                "generate_image",
                                '{"prompt":"A municipal skyline"}',
                            )
                        ]
                    )
                ]
            ),
            messages=[
                {"role": "system", "content": "Base instructions"},
                {"role": "user", "content": "Create an image"},
            ],
            kwargs={"tools": []},
            mcp_proxy=None,
            skill_runtime=runtime,
            has_tools=True,
        )

        output = [
            completion
            async for completion in adapter.iterate_stream(
                stream=prepared,
                model_kwargs={},
            )
        ]

        assert all(
            completion.response_type is not ResponseType.ERROR for completion in output
        )


@pytest.mark.parametrize(
    ("selective_activation_enabled", "skill_key", "expected_reason"),
    [
        (True, "missing", SkillActivationRejectionReason.UNKNOWN_KEY),
        (
            False,
            "skill-1",
            SkillActivationRejectionReason.ACTIVATION_UNAVAILABLE,
        ),
    ],
)
@pytest.mark.asyncio
async def test_streaming_rejected_activation_dispatches_external_sibling(
    selective_activation_enabled: bool,
    skill_key: str,
    expected_reason: SkillActivationRejectionReason,
) -> None:
    adapter = _adapter()
    runtime = _runtime(
        selective_activation_enabled=selective_activation_enabled,
    )
    proxy = _FakeMCPProxy()
    prepared = PreparedModelStream(
        stream=_AsyncChunkStream(
            [
                _tool_chunk(
                    calls=[
                        (
                            "activation-1",
                            SKILL_ACTIVATION_TOOL_NAME,
                            f'{{"skill_key":"{skill_key}"}}',
                        ),
                        (
                            "external-1",
                            "server__lookup",
                            '{"query":"payroll"}',
                        ),
                    ]
                )
            ]
        ),
        messages=[
            {"role": "system", "content": "Base instructions"},
            {"role": "user", "content": "Help with payroll"},
        ],
        kwargs={"tools": []},
        mcp_proxy=proxy,
        skill_runtime=runtime,
        has_tools=True,
    )

    with patch(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        AsyncMock(return_value=_AsyncChunkStream([_text_chunk("Lookup answer")])),
    ):
        output = [
            completion
            async for completion in adapter.iterate_stream(
                stream=prepared,
                model_kwargs={},
            )
        ]

    assert any(completion.text == "Lookup answer" for completion in output)
    assert proxy.calls == [[("server__lookup", {"query": "payroll"})]]
    assert runtime.snapshot().rejected[0].reason is expected_reason


def test_reserved_activation_tool_collision_is_dropped_and_recorded() -> None:
    adapter = object.__new__(TenantModelAdapter)
    adapter.model = SimpleNamespace(
        name="test-model",
        supports_tool_calling=True,
    )
    runtime = _runtime()
    built_in = {
        "type": "function",
        "function": {"name": SKILL_ACTIVATION_TOOL_NAME},
    }
    proxy = _CollisionMCPProxy()

    tools = adapter._merge_mcp_tools([built_in], proxy, runtime)

    assert tools == [built_in]
    assert runtime.snapshot().rejected[0].reason is (
        SkillActivationRejectionReason.RESERVED_TOOL_COLLISION
    )


def test_reserved_activation_tool_collision_is_dropped_during_fallback() -> None:
    adapter = object.__new__(TenantModelAdapter)
    adapter.model = SimpleNamespace(
        name="test-model",
        supports_tool_calling=True,
    )
    runtime = _runtime(selective_activation_enabled=False)
    proxy = _CollisionMCPProxy()

    tools = adapter._merge_mcp_tools([], proxy, runtime)

    assert tools == []
    assert runtime.snapshot().rejected[0].reason is (
        SkillActivationRejectionReason.RESERVED_TOOL_COLLISION
    )
