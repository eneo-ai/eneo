from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    BadRequestError,
    RateLimitError,
    Timeout,
)

from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.completion_service import (
    ResolvedCompletionModelRoute,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderKnownProviderRejectionException,
    AIBuilderProviderOutcomeUnknownException,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import ProposalTurnTelemetry
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


def _pending_question_conversation() -> list[ConversationMessage]:
    return [
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


@pytest.mark.parametrize(
    ("error", "expected_kind", "expected_status_class", "expected_committed"),
    [
        (
            BadRequestError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "rejected",
            "4xx",
            True,
        ),
        (
            RateLimitError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "rate_limited",
            "4xx",
            True,
        ),
        (
            APIError(
                400,
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "rejected",
            "4xx",
            True,
        ),
        (
            Timeout(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "timeout",
            "4xx",
            False,
        ),
        (
            APIConnectionError(
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "transport_ambiguous",
            None,
            False,
        ),
        (
            APIError(
                503,
                "sensitive-provider-material",
                model="private-model",
                llm_provider="private-provider",
            ),
            "transport_ambiguous",
            "5xx",
            False,
        ),
        (RuntimeError("sensitive-provider-material"), "unknown", None, False),
    ],
)
@pytest.mark.asyncio
async def test_semantic_adjudication_provider_failure_uses_typed_disposition(
    error: Exception,
    expected_kind: str,
    expected_status_class: str | None,
    expected_committed: bool,
) -> None:
    litellm_client = MagicMock()
    litellm_client.acompletion = AsyncMock(side_effect=error)
    before_provider_call = AsyncMock()
    usage_tracker = ProposalTurnTelemetry(
        request_id="req-semantic-failure",
        model="openai/gpt-test",
        target_kind=TargetKind.CREATE,
    )

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        await adjudicate_pending_question_answer(
            litellm_client=litellm_client,
            completion_model_route=_route(),
            conversation=_pending_question_conversation(),
            user_message="PDF",
            usage_tracker=usage_tracker,
            before_provider_call=before_provider_call,
        )

    expected_exception = (
        AIBuilderKnownProviderRejectionException
        if expected_committed
        else AIBuilderProviderOutcomeUnknownException
    )
    assert isinstance(exc_info.value, expected_exception)
    assert exc_info.value.public_error is not None
    assert exc_info.value.public_error.details is not None
    assert exc_info.value.public_error.details["another_call_permitted"] is False
    assert exc_info.value.public_error.details["provider_disposition"] == (
        "known_rejection" if expected_committed else "provider_outcome_unknown"
    )
    exception_class = exc_info.value.public_error.details["provider_exception_class"]
    if isinstance(error, APIError):
        assert exception_class == "api_error"
    else:
        assert isinstance(exception_class, str)
    assert exc_info.value.public_error.details["retry_scope"] == (
        "new_turn" if expected_committed else "acknowledged_same_turn"
    )
    before_provider_call.assert_awaited_once_with()
    assert litellm_client.acompletion.await_count == 1
    telemetry = usage_tracker.build_planner_telemetry()
    assert telemetry["llm_calls_made"] == 1
    assert telemetry["auxiliary_llm_call_count"] == 1
    assert telemetry["used_auxiliary_llm"] is True
    assert len(telemetry["call_records"]) == 1
    call_record = telemetry["call_records"][0]
    assert call_record["call_kind"] == "semantic_adjudication"
    assert call_record["provider_failure_kind"] == expected_kind
    assert call_record.get("provider_status_class") == expected_status_class
    assert call_record["provider_turn_state"] == (
        "committed" if expected_committed else "provider_outcome_unknown"
    )
    assert "prompt_tokens" not in call_record
    assert "completion_tokens" not in call_record
    assert "total_tokens" not in call_record
    assert "sensitive-provider-material" not in json.dumps(telemetry)


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
