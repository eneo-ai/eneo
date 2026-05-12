from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.flows.ai_builder import ai_builder_discovery_runtime as runtime
from intric.flows.ai_builder.ai_builder_discovery_runtime import (
    analyze_discovery_runtime,
    build_discovery_block_message_runtime,
    build_runtime_planning_state,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage
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


def _slot(name: str, value: str) -> ResolvedSlot:
    return ResolvedSlot(
        name=name,
        value=value,
        source="structured_answer",
        evidence=[f"question_answer:{name}"],
        confidence="high",
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
    assert state.resolved_slots["runtime_metadata_fields"].value == "basic_case_metadata"


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
    assert "primary_runtime_input" not in prompt
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
    assert "primary_runtime_input" not in prompt


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
