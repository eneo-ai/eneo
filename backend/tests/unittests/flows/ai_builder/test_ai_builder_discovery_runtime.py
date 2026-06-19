from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.flows.ai_builder import ai_builder_discovery_runtime as runtime
from intric.flows.ai_builder.ai_builder_discovery_models import (
    BackendQuestion,
    DiscoveryAnalysis,
)
from intric.flows.ai_builder.ai_builder_discovery_runtime import (
    DiscoveryRuntimeResult,
    RuntimeDiscoveryContext,
    _targeted_classification_bias,
    analyze_discovery_runtime,
    build_discovery_block_message_runtime,
    build_discovery_runtime_result,
    build_runtime_planning_state,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from intric.flows.ai_builder.ai_builder_event_models import (
    StructuredQuestionOptionPayload,
    StructuredQuestionPayload,
)
from intric.flows.ai_builder.ai_builder_slot_classifier import UNKNOWN_SLOT_VALUE
from intric.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    EvidenceRef,
    PlanningState,
    ResolvedSlot,
)


def _make_response(content: str) -> MagicMock:
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _resolved_state() -> PlanningState:
    return PlanningState(
        fcm_version=FCM_VERSION,
        planner_contract_version=PLANNER_CONTRACT_VERSION,
        builder_schema_version=BUILDER_SCHEMA_VERSION,
        phase="discovering",
        evidence=EvidenceRef(),
        resolved_slots={
            "primary_runtime_input": _slot("primary_runtime_input", "text"),
            "terminal_output": _slot("terminal_output", "structured_text"),
            "document_material_scope": _slot(
                "document_material_scope",
                "single_uploaded_document",
            ),
            "post_processing_goal": _slot(
                "post_processing_goal",
                "summarize_or_overview",
            ),
            "structured_analysis_need": _slot(
                "structured_analysis_need",
                "text_only_analysis",
            ),
            "runtime_metadata_fields": _slot(
                "runtime_metadata_fields",
                "no_extra_metadata",
            ),
        },
    )


def _slot(
    name: str,
    value: str,
    *,
    source: str = "structured_answer",
    confidence: str = "high",
) -> ResolvedSlot:
    return ResolvedSlot(
        name=name,
        value=value,
        source=source,
        evidence=[f"question_answer:{name}"],
        confidence=confidence,
    )


@pytest.mark.asyncio
async def test_runtime_planning_state_skips_model_when_resolvable_slots_are_strong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    litellm_client = AsyncMock()
    monkeypatch.setattr(
        runtime,
        "build_planning_state_from_conversation",
        lambda *_args, **_kwargs: _resolved_state(),
    )

    state = await build_runtime_planning_state(
        [ConversationMessage(role="user", content="Skapa ett komplett flöde.")],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
    )

    assert state.resolved_slots.keys() == _resolved_state().resolved_slots.keys()
    litellm_client.acompletion.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_planning_state_classifies_weak_existing_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    weak_state = _resolved_state()
    weak_state.resolved_slots["runtime_metadata_fields"] = ResolvedSlot(
        name="runtime_metadata_fields",
        value="no_extra_metadata",
        source="policy_default",
        evidence=["policy_default:runtime_metadata_fields=no_extra_metadata"],
        confidence="medium",
    )
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "runtime_metadata_fields",
                        "value": "basic_case_metadata",
                        "confidence": "high",
                        "reason": "runtime fields requested",
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(
        runtime,
        "build_planning_state_from_conversation",
        lambda *_args, **_kwargs: weak_state,
    )

    state = await build_runtime_planning_state(
        [
            ConversationMessage(
                role="user",
                content="Användaren ska ange målgrupp och detaljnivå vid körning.",
            )
        ],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
    )

    assert state.resolved_slots["runtime_metadata_fields"].source == "model"
    assert (
        state.resolved_slots["runtime_metadata_fields"].value == "basic_case_metadata"
    )


@pytest.mark.asyncio
async def test_runtime_planning_state_skips_model_when_freeform_text_is_empty() -> None:
    litellm_client = AsyncMock()

    await build_runtime_planning_state(
        [ConversationMessage(role="user", content="   ")],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
    )

    litellm_client.acompletion.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_planning_state_skips_model_when_classification_is_disabled() -> (
    None
):
    litellm_client = AsyncMock()

    await build_runtime_planning_state(
        [ConversationMessage(role="user", content="Bygg ett sammanfattningsflöde.")],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        allow_classification=False,
    )

    litellm_client.acompletion.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_planning_state_overlays_model_slots() -> None:
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "primary_runtime_input",
                        "value": "text",
                        "confidence": "high",
                        "reason": "mentions text input",
                    },
                    {
                        "slot_name": "terminal_output",
                        "value": "structured_text",
                        "confidence": "medium",
                        "reason": "asks for a summary",
                    },
                ]
            }
        )
    )

    state = await build_runtime_planning_state(
        [
            ConversationMessage(
                role="user",
                content=(
                    "Jag vill klistra in ett kundmeddelande och få en tydlig "
                    "sammanfattning."
                ),
            )
        ],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        ui_language="sv",
    )

    assert state.resolved_slots["primary_runtime_input"].source == "heuristic"
    assert state.resolved_slots["primary_runtime_input"].value == "text"
    assert state.resolved_slots["terminal_output"].source == "model"
    assert state.resolved_slots["terminal_output"].value == "structured_text"

    messages = litellm_client.acompletion.await_args.kwargs["messages"]
    prompt = "\n".join(message["content"] for message in messages)
    assert "\n- primary_runtime_input:" not in prompt
    assert "terminal_output" in prompt


@pytest.mark.asyncio
async def test_runtime_planning_state_accepts_model_classified_json_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "primary_runtime_input",
                        "value": "json",
                        "confidence": "high",
                        "reason": "the runtime source is a JSON payload",
                    },
                    {
                        "slot_name": "terminal_output",
                        "value": "structured_json",
                        "confidence": "high",
                        "reason": "the user asks for JSON output",
                    },
                ]
            }
        )
    )
    monkeypatch.setattr(
        runtime,
        "build_planning_state_from_conversation",
        lambda *_args, **_kwargs: PlanningState.empty(),
    )

    state = await build_runtime_planning_state(
        [
            ConversationMessage(
                role="user",
                content="Jag vill bygga ett flöde som tar emot JSON och returnerar JSON.",
            )
        ],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        ui_language="sv",
    )

    assert state.resolved_slots["primary_runtime_input"].value == "json"
    assert state.resolved_slots["terminal_output"].value == "structured_json"

    messages = litellm_client.acompletion.await_args.kwargs["messages"]
    prompt = "\n".join(message["content"] for message in messages)
    assert "\n- primary_runtime_input:" in prompt
    assert "json" in prompt


@pytest.mark.asyncio
async def test_runtime_planning_state_clears_nonprotected_output_guess_on_uncertainty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    heuristic_state = PlanningState.empty()
    heuristic_state.phase = "discovering"
    heuristic_state.resolved_slots = {
        "primary_runtime_input": _slot(
            "primary_runtime_input",
            "audio",
            source="heuristic",
            confidence="high",
        ),
        "terminal_output": _slot(
            "terminal_output",
            "structured_text",
            source="heuristic",
            confidence="medium",
        ),
    }
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "terminal_output",
                        "value": UNKNOWN_SLOT_VALUE,
                        "confidence": "high",
                        "reason": "user_explicit_uncertain",
                    },
                ],
            }
        )
    )
    monkeypatch.setattr(
        runtime,
        "build_planning_state_from_conversation",
        lambda *_args, **_kwargs: heuristic_state,
    )

    state = await build_runtime_planning_state(
        [
            ConversationMessage(
                role="user",
                content=(
                    "Jag har en svensk ljudinspelning från ett möte. Jag vet "
                    "inte exakt vilket format slutresultatet ska vara ännu."
                ),
                metadata={"ui_language": "sv"},
            )
        ],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        ui_language="sv",
    )

    assert state.resolved_slots["primary_runtime_input"].value == "audio"
    assert "terminal_output" not in state.resolved_slots
    messages = litellm_client.acompletion.await_args.kwargs["messages"]
    prompt = "\n".join(message["content"] for message in messages)
    assert "terminal_output" in prompt


@pytest.mark.asyncio
async def test_runtime_planning_state_does_not_let_model_override_structured_answer() -> (
    None
):
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "primary_runtime_input",
                        "value": "documents",
                        "confidence": "high",
                        "reason": "incorrect model guess",
                    },
                    {
                        "slot_name": "terminal_output",
                        "value": "structured_text",
                        "confidence": "high",
                        "reason": "summary requested",
                    },
                ]
            }
        )
    )

    state = await build_runtime_planning_state(
        [
            ConversationMessage(
                role="user",
                content="Text",
                metadata={
                    "question_answer": {
                        "question_id": "input_material_mode",
                        "selected_values": ["text"],
                    }
                },
            ),
            ConversationMessage(
                role="user",
                content="Bygg ett flöde som sammanfattar innehållet tydligt.",
            ),
        ],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        ui_language="sv",
    )

    assert state.resolved_slots["primary_runtime_input"].source == "structured_answer"
    assert state.resolved_slots["primary_runtime_input"].value == "text"

    messages = litellm_client.acompletion.await_args.kwargs["messages"]
    prompt = "\n".join(message["content"] for message in messages)
    assert "\n- primary_runtime_input:" not in prompt


@pytest.mark.asyncio
async def test_runtime_discovery_uses_llm_baseline_for_natural_swedish_support_flow() -> (
    None
):
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "primary_runtime_input",
                        "value": "text",
                        "confidence": "high",
                        "reason": "the source material is user-provided prose",
                    },
                    {
                        "slot_name": "terminal_output",
                        "value": "structured_json",
                        "confidence": "high",
                        "reason": "structured data is requested for downstream use",
                    },
                ]
            }
        )
    )

    analysis = await analyze_discovery_runtime(
        [
            ConversationMessage(
                role="user",
                content=(
                    "Gör ett smart supportflöde där användaren klistrar in ett "
                    "kundmeddelande, klassificerar avsikt och prioritet, föreslår "
                    "svar, markerar om mänsklig granskning behövs och returnerar "
                    "både kort text och strukturerad data."
                ),
                metadata={"ui_language": "sv"},
            )
        ],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        ui_language="sv",
    )

    question_ids = {
        issue.suggestion.question_id
        for issue in analysis.blocking_issues
        if issue.suggestion is not None
    }
    assert "input_material_mode" not in question_ids
    assert "final_output_mode" not in question_ids
    assert analysis.ready_for_confirmation is True

    messages = litellm_client.acompletion.await_args.kwargs["messages"]
    prompt = "\n".join(message["content"] for message in messages)
    assert "primary_runtime_input" in prompt
    assert "terminal_output" in prompt


@pytest.mark.asyncio
async def test_runtime_discovery_asks_output_question_when_model_guesses_uncertain_output() -> (
    None
):
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "primary_runtime_input",
                        "value": "audio",
                        "confidence": "high",
                        "reason": "the source material is a meeting recording",
                    },
                    {
                        "slot_name": "terminal_output",
                        "value": "structured_text",
                        "confidence": "high",
                        "reason": "a readable result is implied",
                    },
                ],
            }
        )
    )

    analysis = await analyze_discovery_runtime(
        [
            ConversationMessage(
                role="user",
                content=(
                    "Jag har en svensk ljudinspelning från ett möte och vill "
                    "göra ett flöde av den. Flödet ska ta ljudfilen, förstå "
                    "vad som sades och skapa något användbart som jag kan dela "
                    "vidare efteråt. Jag vet inte exakt vilket format "
                    "slutresultatet ska vara ännu."
                ),
                metadata={"ui_language": "sv"},
            )
        ],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        ui_language="sv",
    )

    question_ids = {
        issue.suggestion.question_id
        for issue in analysis.blocking_issues
        if issue.suggestion is not None
    }
    assert "final_output_mode" in question_ids
    assert analysis.ready_for_confirmation is False

    messages = litellm_client.acompletion.await_args.kwargs["messages"]
    prompt = "\n".join(message["content"] for message in messages)
    assert "\n- terminal_output:" not in prompt


@pytest.mark.asyncio
async def test_runtime_discovery_uses_llm_baseline_for_swedish_document_json_flow() -> (
    None
):
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "primary_runtime_input",
                        "value": "documents",
                        "confidence": "high",
                        "reason": "the source material is uploaded documents",
                    },
                    {
                        "slot_name": "document_material_scope",
                        "value": "multiple_documents_case",
                        "confidence": "high",
                        "reason": "the user says several related files",
                    },
                    {
                        "slot_name": "terminal_output",
                        "value": "structured_json",
                        "confidence": "high",
                        "reason": "structured JSON is requested for another system",
                    },
                ]
            }
        )
    )

    analysis = await analyze_discovery_runtime(
        [
            ConversationMessage(
                role="user",
                content=(
                    "Skapa ett flöde som tar emot flera leverantörsavtal och bilagor, "
                    "extraherar risker, rekommendationer och öppna frågor, "
                    "låter en människa granska, och returnerar strukturerad "
                    "JSON för ett uppföljningssystem."
                ),
                metadata={"ui_language": "sv"},
            )
        ],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        ui_language="sv",
    )

    question_ids = {
        issue.suggestion.question_id
        for issue in analysis.blocking_issues
        if issue.suggestion is not None
    }
    assert "input_material_mode" not in question_ids
    assert "document_material_scope" not in question_ids
    assert "final_output_mode" not in question_ids
    assert analysis.ready_for_confirmation is True


@pytest.mark.asyncio
async def test_discovery_block_runtime_uses_one_classification_for_analysis_and_state() -> (
    None
):
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "primary_runtime_input",
                        "value": "text",
                        "confidence": "high",
                        "reason": "the user provides text",
                    },
                    {
                        "slot_name": "terminal_output",
                        "value": "structured_text",
                        "confidence": "high",
                        "reason": "a readable summary is requested",
                    },
                ]
            }
        )
    )

    message, analysis, planning_state = await build_discovery_block_message_runtime(
        [
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde där användaren klistrar in intervjusvar och får "
                    "en läsbar sammanfattning med viktiga teman."
                ),
                metadata={"ui_language": "sv"},
            )
        ],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        ui_language="sv",
    )

    assert message is None
    assert analysis.ready_for_confirmation is True
    assert planning_state.resolved_slots["primary_runtime_input"].source == "model"
    assert planning_state.resolved_slots["terminal_output"].source == "model"
    litellm_client.acompletion.assert_awaited_once()


def _clarification_question(question_id: str = "terminal_output") -> BackendQuestion:
    return BackendQuestion(
        question_data=StructuredQuestionPayload(
            question_id=question_id,
            question="Vilket format ska slutresultatet ha?",
            options=[StructuredQuestionOptionPayload(label="PDF")],
            selection_mode="single",
            allow_custom=True,
        ),
        assistant_text="Jag behöver förstå slutresultatet.",
    )


def test_targeted_bias_maps_legacy_question_id_to_slot() -> None:
    bias = _targeted_classification_bias(
        [
            ConversationMessage(
                role="assistant",
                content="Vilket format?",
                metadata={"question_id": "final_output_mode"},
            ),
            ConversationMessage(role="user", content="en fil jag kan ladda ner"),
        ],
        {"terminal_output": {"docx_document", "structured_text"}},
    )

    assert bias is not None
    assert bias.target_slot_name == "terminal_output"
    assert bias.asked_question_id == "final_output_mode"
    assert bias.latest_user_answer == "en fil jag kan ladda ner"


def test_targeted_bias_is_none_when_target_already_resolved() -> None:
    bias = _targeted_classification_bias(
        [
            ConversationMessage(
                role="assistant",
                content="Vilket format?",
                metadata={"question_id": "final_output_mode"},
            ),
            ConversationMessage(role="user", content="en fil"),
        ],
        {"primary_runtime_input": {"text", "documents"}},
    )

    assert bias is None


async def _run_with_followup(
    conversation: list[ConversationMessage],
) -> tuple[DiscoveryRuntimeResult, AsyncMock]:
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        "Omformulerad ledtext med PDF-exempel."
    )
    with (
        patch.object(
            runtime,
            "build_runtime_discovery_context",
            new_callable=AsyncMock,
            return_value=RuntimeDiscoveryContext(planning_state=PlanningState.empty()),
        ),
        patch.object(
            runtime, "analyze_discovery", return_value=DiscoveryAnalysis(issues=())
        ),
        patch.object(
            runtime, "build_discovery_followup", return_value=_clarification_question()
        ),
        patch.object(runtime, "build_discovery_block_message", return_value=None),
    ):
        result = await build_discovery_runtime_result(
            conversation,
            litellm_client=litellm_client,
            litellm_model="gpt-test",
            tenant_id=uuid4(),
        )
    return result, litellm_client


@pytest.mark.asyncio
async def test_reask_keeps_catalog_text_without_llm_call() -> None:
    conversation = [
        ConversationMessage(role="user", content="Bygg ett flöde."),
        ConversationMessage(
            role="assistant",
            content="Vilket format?",
            metadata={"question_id": "terminal_output"},
        ),
        ConversationMessage(role="user", content="vet inte"),
    ]

    result, litellm_client = await _run_with_followup(conversation)

    litellm_client.acompletion.assert_not_awaited()
    assert result.followup is not None
    assert result.followup.assistant_text == "Jag behöver förstå slutresultatet."
    assert result.followup.question_data.question_id == "terminal_output"
    assert (
        result.followup.question_data.question == "Vilket format ska slutresultatet ha?"
    )
    assert [o.label for o in result.followup.question_data.options] == ["PDF"]


@pytest.mark.asyncio
async def test_first_ask_keeps_catalog_text_without_llm_call() -> None:
    conversation = [ConversationMessage(role="user", content="Bygg ett flöde.")]

    result, litellm_client = await _run_with_followup(conversation)

    litellm_client.acompletion.assert_not_awaited()
    assert result.followup is not None
    assert result.followup.assistant_text == "Jag behöver förstå slutresultatet."
