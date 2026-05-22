from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from intric.flows.ai_builder.ai_builder_create_outline import OUTLINE_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_proposal_completion import (
    call_proposal_completion,
    make_usage_tracked_proposal_completion,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
)


def _make_response_with_text(
    text: str,
    *,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
):
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text, tool_calls=None),
                finish_reason="stop",
            )
        ],
    )
    if prompt_tokens is not None:
        response.usage = SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    return response


@pytest.mark.asyncio
async def test_call_proposal_completion_strips_planner_response_format_kwargs() -> None:
    response = _make_response_with_text("ok")
    litellm_client = SimpleNamespace(acompletion=AsyncMock(return_value=response))

    result = await call_proposal_completion(
        litellm_client=litellm_client,
        messages=[{"role": "user", "content": "Build a flow"}],
        tool_schemas=[{"function": {"name": OUTLINE_FLOW_TOOL_NAME}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={
            "response_format": {"type": "json_object"},
            "drop_params": False,
            "api_base": "http://provider.example",
        },
        max_output_tokens=1024,
        temperature=0.2,
    )

    assert result is response
    call_kwargs = litellm_client.acompletion.await_args.kwargs
    assert call_kwargs["api_base"] == "http://provider.example"
    assert "response_format" not in call_kwargs


@pytest.mark.asyncio
async def test_call_proposal_completion_forces_drop_params_true_on_provider_call() -> (
    None
):
    response = _make_response_with_text("ok")
    litellm_client = SimpleNamespace(acompletion=AsyncMock(return_value=response))

    await call_proposal_completion(
        litellm_client=litellm_client,
        messages=[{"role": "user", "content": "Build a flow"}],
        tool_schemas=[{"function": {"name": OUTLINE_FLOW_TOOL_NAME}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={"drop_params": False},
        max_output_tokens=1024,
        temperature=0.2,
    )

    call_kwargs = litellm_client.acompletion.await_args.kwargs
    assert call_kwargs["drop_params"] is True


@pytest.mark.asyncio
async def test_usage_tracked_completion_records_non_repair_usage() -> None:
    response = _make_response_with_text(
        "ok",
        prompt_tokens=5,
        completion_tokens=3,
        total_tokens=8,
    )
    litellm_client = SimpleNamespace(acompletion=AsyncMock(return_value=response))
    tracker = ProposalTurnTelemetry(
        request_id="req-non-repair",
        model="openai/gpt-5.4",
    )
    completion = make_usage_tracked_proposal_completion(
        litellm_client=litellm_client,
        usage_tracker=tracker,
        counts_as_repair=False,
    )

    result = await completion(
        messages=[{"role": "user", "content": "Build a flow"}],
        tool_schemas=[{"function": {"name": OUTLINE_FLOW_TOOL_NAME}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        max_output_tokens=1024,
        temperature=0.2,
    )

    assert result is response
    telemetry = tracker.build_planner_telemetry(tool_call_count=0)
    assert telemetry["llm_calls_made"] == 1
    assert telemetry["total_tokens"] == 8
    assert telemetry["repair_attempts"] == 0


@pytest.mark.asyncio
async def test_usage_tracked_completion_counts_repair_usage() -> None:
    response = _make_response_with_text(
        "ok",
        prompt_tokens=6,
        completion_tokens=4,
        total_tokens=10,
    )
    litellm_client = SimpleNamespace(acompletion=AsyncMock(return_value=response))
    tracker = ProposalTurnTelemetry(
        request_id="req-repair",
        model="openai/gpt-5.4",
    )
    completion = make_usage_tracked_proposal_completion(
        litellm_client=litellm_client,
        usage_tracker=tracker,
        counts_as_repair=True,
    )

    result = await completion(
        messages=[{"role": "user", "content": "Repair the proposal"}],
        tool_schemas=[{"function": {"name": OUTLINE_FLOW_TOOL_NAME}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        max_output_tokens=1024,
        temperature=0.2,
    )

    assert result is response
    telemetry = tracker.build_planner_telemetry(tool_call_count=0)
    assert telemetry["llm_calls_made"] == 1
    assert telemetry["total_tokens"] == 10
    assert telemetry["repair_attempts"] == 1
