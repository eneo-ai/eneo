from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from intric.flows.ai_builder.ai_builder_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_semantic_adjudication import (
    adjudicate_pending_question_answer,
)


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
        json.dumps(
            {"selected_option_id": "pdf_document", "reason": "mentions a PDF report"}
        )
    )
    conversation = [
        ConversationMessage(
            role="assistant",
            content=None,
            tool_calls=[
                {
                    "id": "tool-1",
                    "name": "ask_structured_question",
                    "arguments": {
                        "question_id": "final_output_mode",
                        "question": "Vad ska flödet producera som slutresultat?",
                        "options": [
                            {
                                "id": "structured_text",
                                "label": "Text",
                                "value": "structured_text",
                            },
                            {
                                "id": "pdf_document",
                                "label": "PDF",
                                "value": "pdf_document",
                            },
                        ],
                    },
                }
            ],
        )
    ]

    result = await adjudicate_pending_question_answer(
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        conversation=conversation,
        user_message="Jag vill ha det som en pdf-rapport.",
    )

    assert result is not None
    assert result.question_id == "final_output_mode"
    assert result.selected_option_ids == ("pdf_document",)
    assert result.selected_values == ("pdf_document",)
    assert result.to_question_answer() == {
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
            tool_calls=[
                {
                    "id": "tool-1",
                    "name": "ask_structured_question",
                    "arguments": {
                        "question_id": "final_output_mode",
                        "question": "Vad ska flödet producera som slutresultat?",
                        "options": [
                            {
                                "id": "structured_text",
                                "label": "Text",
                                "value": "structured_text",
                            },
                            {
                                "id": "pdf_document",
                                "label": "PDF",
                                "value": "pdf_document",
                            },
                        ],
                    },
                }
            ],
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
