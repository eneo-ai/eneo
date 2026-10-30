"""The adapter's handling of the question tool in a streamed turn: a shown
question ends the turn, a refused one goes back to the model, and other
calls of the round wait."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from eneo.ai_models.completion_models.completion_model import (
    ResponseType,
    function_definition_to_tool,
)
from eneo.completion_models.domain.user_questions import (
    ASK_USER_TOOL_NAME,
    QUESTION_TOOL_NAME,
    QUESTIONS_SERVER_NAME,
    ask_user_function_definition,
)
from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    PreparedModelStream,
    TenantModelAdapter,
)
from tests.unit.test_tenant_model_adapter_skill_activation import (
    _adapter,
    _AsyncChunkStream,
    _FakeMCPProxy,
    _text_chunk,
    _tool_chunk,
    declared_capabilities,
)

__all__ = ["declared_capabilities"]

ASK_TOOL = function_definition_to_tool(ask_user_function_definition())
QUESTION = {
    "question": "Vem ska läsa PM:et?",
    "header": "Mottagare",
    "options": [
        {"label": "Nämnden", "description": "Beslutsunderlag."},
        {"label": "Ledningen", "description": None},
    ],
    "multi_select": False,
}
COMPLETION_CALL = (
    "eneo.completion_models.infrastructure.adapters."
    "tenant_model_adapter._acompletion_call"
)


def _prepared(
    chunks: list[object], *, mcp_proxy: _FakeMCPProxy | None = None
) -> PreparedModelStream:
    tools = [ASK_TOOL, *(mcp_proxy.get_tools_for_llm() if mcp_proxy else [])]
    return PreparedModelStream(
        stream=_AsyncChunkStream(chunks),
        messages=[
            {"role": "system", "content": "Base instructions"},
            {"role": "user", "content": "Skriv en PM"},
        ],
        kwargs={"tools": tools},
        mcp_proxy=mcp_proxy,
        skill_runtime=None,
        has_tools=True,
        eneo_tools=[ASK_TOOL],
    )


async def _run(adapter: TenantModelAdapter, prepared: PreparedModelStream):
    return [
        completion
        async for completion in adapter.iterate_stream(stream=prepared, model_kwargs={})
    ]


def _question_steps(output):
    return [
        metadata
        for completion in output
        if completion.response_type is ResponseType.TOOL_CALL
        for metadata in completion.tool_calls_metadata or []
        if metadata.server_name == QUESTIONS_SERVER_NAME
    ]


@pytest.mark.usefixtures("declared_capabilities")
async def test_a_shown_question_ends_the_turn_as_its_last_step() -> None:
    adapter = _adapter()
    prepared = _prepared(
        [
            _tool_chunk(
                calls=[("ask-1", ASK_USER_TOOL_NAME, json.dumps(QUESTION))],
                content="Innan jag skriver behöver jag veta en sak.",
            )
        ]
    )

    with patch(COMPLETION_CALL, AsyncMock()) as completion_call:
        output = await _run(adapter, prepared)

    # No follow-up request: the person's answer is the next message.
    completion_call.assert_not_awaited()
    assert [c.text for c in output if c.text] == [
        "Innan jag skriver behöver jag veta en sak."
    ]
    (step,) = _question_steps(output)
    assert step.tool_call_id == "ask-1"
    assert step.tool_name == QUESTION_TOOL_NAME
    assert step.mcp_tool_name == ASK_USER_TOOL_NAME
    assert step.is_internal is True
    assert step.result_status == "succeeded"
    assert step.structured_content == QUESTION
    assert step.arguments == QUESTION
    assert json.loads(step.result or "")["asked"] is True
    # The turn closes normally, with its usage, not as a tool-round failure.
    assert output[-1].stop is True
    assert output[-1].response_type is not ResponseType.ERROR
    # The transcript holds the call and its result for this turn's record.
    assert prepared.messages[-2]["role"] == "assistant"
    assert prepared.messages[-2]["tool_calls"][0]["id"] == "ask-1"
    assert prepared.messages[-1] == {
        "role": "tool",
        "tool_call_id": "ask-1",
        "content": step.result,
    }


@pytest.mark.usefixtures("declared_capabilities")
async def test_a_question_the_chat_cannot_show_goes_back_to_the_model() -> None:
    adapter = _adapter()
    one_option = {**QUESTION, "options": QUESTION["options"][:1]}
    prepared = _prepared(
        [_tool_chunk(calls=[("ask-1", ASK_USER_TOOL_NAME, json.dumps(one_option))])]
    )

    with patch(
        COMPLETION_CALL,
        AsyncMock(return_value=_AsyncChunkStream([_text_chunk("Då gissar jag.")])),
    ) as completion_call:
        output = await _run(adapter, prepared)

    (step,) = _question_steps(output)
    assert step.result_status == "failed"
    assert step.structured_content is None
    refusal = json.loads(step.result or "")
    assert refusal["asked"] is False
    assert "between 2 and 4 options" in refusal["error"]
    # The model reads the refusal and continues in the same turn.
    follow_up_messages = completion_call.await_args.kwargs["messages"]
    assert follow_up_messages[-1] == {
        "role": "tool",
        "tool_call_id": "ask-1",
        "content": step.result,
    }
    assert [c.text for c in output if c.text] == ["Då gissar jag."]


@pytest.mark.usefixtures("declared_capabilities")
async def test_other_calls_of_the_round_wait_for_the_answer() -> None:
    adapter = _adapter()
    proxy = _FakeMCPProxy()
    prepared = _prepared(
        [
            _tool_chunk(
                calls=[
                    ("lookup-1", "server__lookup", '{"query":"remiss"}'),
                    ("ask-1", ASK_USER_TOOL_NAME, json.dumps(QUESTION)),
                ]
            )
        ],
        mcp_proxy=proxy,
    )

    with patch(COMPLETION_CALL, AsyncMock()) as completion_call:
        output = await _run(adapter, prepared)

    completion_call.assert_not_awaited()
    assert proxy.calls == []
    steps = {
        metadata.tool_call_id: metadata
        for completion in output
        if completion.response_type is ResponseType.TOOL_CALL
        for metadata in completion.tool_calls_metadata or []
    }
    assert steps["ask-1"].result_status == "succeeded"
    assert steps["lookup-1"].result_status == "deferred"
    assert steps["lookup-1"].server_name == "server"
    assert json.loads(steps["lookup-1"].result or "") == {
        "deferred": True,
        "reason": "question_pending",
        "retryable": True,
    }


@pytest.mark.usefixtures("declared_capabilities")
async def test_only_the_first_question_of_a_round_is_shown() -> None:
    adapter = _adapter()
    prepared = _prepared(
        [
            _tool_chunk(
                calls=[
                    ("ask-1", ASK_USER_TOOL_NAME, json.dumps(QUESTION)),
                    ("ask-2", ASK_USER_TOOL_NAME, json.dumps(QUESTION)),
                ]
            )
        ]
    )

    with patch(COMPLETION_CALL, AsyncMock()):
        output = await _run(adapter, prepared)

    first, second = _question_steps(output)
    assert first.result_status == "succeeded"
    assert second.result_status == "failed"
    assert "one question per turn" in json.loads(second.result or "")["error"]


def test_an_external_tool_named_like_the_question_tool_is_not_offered() -> None:
    adapter = _adapter()
    adapter._merge_mcp_tools = Mock(
        side_effect=lambda *args, **kwargs: TenantModelAdapter._merge_mcp_tools(
            adapter, *args, **kwargs
        )
    )

    class _Collision(_FakeMCPProxy):
        def get_tools_for_llm(self) -> list[dict[str, object]]:
            return [
                {"type": "function", "function": {"name": ASK_USER_TOOL_NAME}},
                {"type": "function", "function": {"name": "server__lookup"}},
            ]

    tools = adapter._merge_mcp_tools([], _Collision())
    assert [tool["function"]["name"] for tool in tools] == ["server__lookup"]


def test_without_the_tool_the_turn_offers_no_question() -> None:
    assert (
        TenantModelAdapter._offers_questions(
            SimpleNamespace(eneo_tools=[{"type": "function", "function": {}}])  # type: ignore[arg-type]
        )
        is False
    )
    assert TenantModelAdapter._offers_questions(None) is False
    assert (
        TenantModelAdapter._offers_questions(
            SimpleNamespace(eneo_tools=[ASK_TOOL])  # type: ignore[arg-type]
        )
        is True
    )
