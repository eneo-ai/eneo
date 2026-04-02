from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock

from intric.flows.ai_builder.ai_builder_proposal_repair import (
    retry_forced_tool_after_text,
)


def _tool_response(*, tool_name: str, arguments: dict[str, object]) -> SimpleNamespace:
    tool_call = SimpleNamespace(
        id="call_create",
        function=SimpleNamespace(
            name=tool_name,
            arguments=json.dumps(arguments),
        ),
    )
    message = SimpleNamespace(content=None, tool_calls=[tool_call])
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


@pytest.mark.asyncio
async def test_retry_forced_tool_after_text_does_not_inject_flow_into_processors_that_do_not_accept_it() -> None:
    processed_arguments: dict[str, object] = {}

    async def process_create_arguments(
        *,
        session_id,
        conversation,
        new_messages_start,
        arguments,
        assistant_content,
        tool_call_id,
        available_model_refs,
        available_kb_refs,
    ):
        processed_arguments.update(arguments)
        return SimpleNamespace(event={"event": "plan", "data": "{}"}, feedback=None, failure_kind=None)

    result = await retry_forced_tool_after_text(
        correction_messages=[{"role": "system", "content": "Prompt"}],
        assistant_text="Här är mitt förslag.",
        tool_schemas=[{"function": {"name": "create_flow"}}],
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        session_id=uuid4(),
        conversation=[],
        new_messages_start=0,
        available_model_refs=None,
        available_kb_refs=None,
        max_output_tokens=1024,
        target_tool_name="create_flow",
        forced_tool_prompt="Call create_flow.",
        forced_proposal_temperature=0.1,
        call_repair_completion=AsyncMock(
            return_value=_tool_response(
                tool_name="create_flow",
                arguments={"flow_name": "Test", "plan_rationale": "R", "steps": []},
            )
        ),
        process_tool_arguments=process_create_arguments,
        process_tool_kwargs=None,
        flow=None,
    )

    assert result == {"event": "plan", "data": "{}"}
    assert processed_arguments["flow_name"] == "Test"
