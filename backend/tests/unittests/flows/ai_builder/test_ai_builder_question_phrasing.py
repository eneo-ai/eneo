from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_question_phrasing import (
    phrase_clarification_question,
)


def _make_response(content: str | None) -> MagicMock:
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


async def _phrase(client: AsyncMock, *, ask_count: int = 0) -> str | None:
    return await phrase_clarification_question(
        litellm_client=client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        baseline_text="Vilket format ska slutresultatet ha?",
        question_id="terminal_output",
        ask_count=ask_count,
        ui_language="sv",
        tenant_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_phrasing_returns_the_model_rewrite() -> None:
    client = AsyncMock()
    client.acompletion.return_value = _make_response(
        "Vill du ha resultatet som PDF eller bara text? (PDF passar en rapport.)"
    )

    phrased = await _phrase(client)

    assert (
        phrased
        == "Vill du ha resultatet som PDF eller bara text? (PDF passar en rapport.)"
    )


@pytest.mark.asyncio
async def test_phrasing_falls_back_to_none_on_llm_failure() -> None:
    client = AsyncMock()
    client.acompletion.side_effect = RuntimeError("llm down")

    assert await _phrase(client) is None


@pytest.mark.asyncio
async def test_phrasing_falls_back_to_none_on_empty_content() -> None:
    client = AsyncMock()
    client.acompletion.return_value = _make_response("   ")

    assert await _phrase(client) is None


@pytest.mark.asyncio
async def test_phrasing_escalates_wording_when_already_asked() -> None:
    client = AsyncMock()
    client.acompletion.return_value = _make_response("Annan formulering")

    await _phrase(client, ask_count=1)

    user_prompt = client.acompletion.await_args.kwargs["messages"][-1]["content"]
    assert "differently" in user_prompt


@pytest.mark.asyncio
async def test_phrasing_skips_escalation_on_first_ask() -> None:
    client = AsyncMock()
    client.acompletion.return_value = _make_response("Formulering")

    await _phrase(client, ask_count=0)

    user_prompt = client.acompletion.await_args.kwargs["messages"][-1]["content"]
    assert "differently" not in user_prompt
