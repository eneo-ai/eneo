from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.completion_service import (
    ResolvedCompletionModelRoute,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_semantic_adjudication import (
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


def _route(
    *, supported: SupportedModelKwargs | None = None
) -> ResolvedCompletionModelRoute:
    return ResolvedCompletionModelRoute(
        litellm_model="openai/gpt-test",
        litellm_kwargs={},
        supported_model_kwargs=supported
        or SupportedModelKwargs(temperature=ModelKwargCapability(supported=True)),
    )


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
                        "question_id": "terminal_output",
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
        completion_model_route=_route(),
        conversation=conversation,
        user_message="Jag vill ha det som en pdf-rapport.",
    )

    assert result is not None
    assert result.question_id == "terminal_output"
    assert result.selected_option_ids == ("pdf_document",)
    assert result.selected_values == ("pdf_document",)
    assert result.to_question_answer() == {
        "question_id": "terminal_output",
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
                        "question_id": "terminal_output",
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
        completion_model_route=_route(),
        conversation=conversation,
        user_message="asdfgh",
    )

    assert result is None


@pytest.mark.asyncio
async def test_adjudication_filters_temperature_and_starts_immediately_before_call() -> (
    None
):
    events: list[str] = []

    async def complete(**_kwargs: object) -> MagicMock:
        events.append("provider")
        return _make_response(
            json.dumps({"selected_option_id": "pdf_document", "reason": "PDF"})
        )

    async def mark_provider_started() -> None:
        events.append("started")

    litellm_client = MagicMock()
    litellm_client.acompletion = AsyncMock(side_effect=complete)
    conversation = [
        ConversationMessage(
            role="assistant",
            content=None,
            tool_calls=[
                {
                    "id": "tool-1",
                    "name": "ask_structured_question",
                    "arguments": {
                        "question_id": "terminal_output",
                        "question": "Output?",
                        "options": [
                            {
                                "id": "pdf_document",
                                "label": "PDF",
                                "value": "pdf_document",
                            }
                        ],
                    },
                }
            ],
        )
    ]

    result = await adjudicate_pending_question_answer(
        litellm_client=litellm_client,
        completion_model_route=_route(supported=SupportedModelKwargs()),
        conversation=conversation,
        user_message="PDF",
        before_provider_call=mark_provider_started,
    )

    assert result is not None
    assert events == ["started", "provider"]
    assert litellm_client.acompletion.await_count == 1
    assert "temperature" not in litellm_client.acompletion.await_args.kwargs
