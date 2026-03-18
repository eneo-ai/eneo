from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_semantic_adjudication import (
    adjudicate_discovery_semantics,
    adjudicate_pending_question_answer,
    should_run_semantic_adjudication,
)
from intric.flows.ai_builder.ai_builder_discovery_models import DiscoveryAnalysis, DiscoveryCandidate


def _make_response(content: str) -> MagicMock:
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.mark.asyncio
async def test_pending_question_adjudication_resolves_paraphrase() -> None:
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps({"selected_option_id": "pdf_document", "reason": "mentions a PDF report"})
    )
    conversation = [
        ConversationMessage(
            role="assistant",
            content=None,
            tool_calls=[{
                "id": "tool-1",
                "name": "ask_structured_question",
                "arguments": {
                    "question_id": "final_output_mode",
                    "question": "Vad ska flödet producera som slutresultat?",
                    "options": [
                        {"id": "structured_text", "label": "Text", "value": "structured_text"},
                        {"id": "pdf_document", "label": "PDF", "value": "pdf_document"},
                    ],
                },
            }],
        )
    ]

    result = await adjudicate_pending_question_answer(
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        conversation=conversation,
        user_message="Jag vill ha det som en pdf-rapport.",
    )

    assert result == {
        "question_id": "final_output_mode",
        "selected_option_ids": ["pdf_document"],
        "selected_values": ["pdf_document"],
    }


@pytest.mark.asyncio
async def test_pending_question_adjudication_rejects_invalid_option() -> None:
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps({"selected_option_id": "not-a-real-option", "reason": "bad"})
    )
    conversation = [
        ConversationMessage(
            role="assistant",
            content=None,
            tool_calls=[{
                "id": "tool-1",
                "name": "ask_structured_question",
                "arguments": {
                    "question_id": "final_output_mode",
                    "question": "Vad ska flödet producera som slutresultat?",
                    "options": [
                        {"id": "structured_text", "label": "Text", "value": "structured_text"},
                        {"id": "pdf_document", "label": "PDF", "value": "pdf_document"},
                    ],
                },
            }],
        )
    ]

    result = await adjudicate_pending_question_answer(
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        conversation=conversation,
        user_message="asdfgh",
    )

    assert result is None


@pytest.mark.asyncio
async def test_discovery_semantic_adjudication_returns_none_on_llm_failure() -> None:
    litellm_client = AsyncMock()
    litellm_client.acompletion.side_effect = RuntimeError("boom")

    result = await adjudicate_discovery_semantics(
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        conversation=[ConversationMessage(role="user", content="Jag vill ha PDF.", tool_calls=None)],
        analysis=DiscoveryAnalysis(
            issues=(),
            mvs_met=True,
            candidates=(
                DiscoveryCandidate(
                    issue_id="final_output_mode",
                    question_id="final_output_mode",
                    confidence="low",
                    impact="quality",
                    assumption_safe=False,
                    family="output",
                    resolved_by="heuristic_assumption",
                ),
            ),
        ),
    )

    assert result is None


def test_should_run_semantic_adjudication_requires_mvs_and_low_confidence_candidate() -> None:
    assert should_run_semantic_adjudication(
        DiscoveryAnalysis(
            issues=(),
            mvs_met=False,
            candidates=(
                DiscoveryCandidate(
                    issue_id="final_output_mode",
                    question_id="final_output_mode",
                    confidence="low",
                    impact="quality",
                    assumption_safe=False,
                    family="output",
                    resolved_by="heuristic_assumption",
                )
            ),
        )
    ) is False
