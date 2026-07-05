from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.files.file_models import FileType
from eneo.flows.ai_builder import ai_builder_discovery_runtime as runtime
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AIBuilderAttachmentContext,
    AIBuilderAttachmentEvidence,
)
from eneo.flows.ai_builder.ai_builder_discovery_runtime import (
    _targeted_classification_bias,
    analyze_discovery_runtime,
    build_discovery_block_message_runtime,
    build_runtime_planning_state,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_slot_classifier import UNKNOWN_SLOT_VALUE
from eneo.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
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


def _attachment_context() -> AIBuilderAttachmentContext:
    return AIBuilderAttachmentContext(
        context=None,
        discovery_context=(
            "Unconfirmed uploaded-file evidence:\n"
            "filename: beslutsmall.docx\n"
            "file_type: document\n"
            "mimetype: application/vnd.openxmlformats-officedocument.wordprocessingml.document\n"
            "has_readable_text: false"
        ),
        evidence=(
            AIBuilderAttachmentEvidence(
                file_id=uuid4(),
                filename="beslutsmall.docx",
                file_type=FileType.DOCUMENT,
                mimetype=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                has_readable_text=False,
                excerpt=None,
                inferred_role="template",
                role_confidence="medium",
                role_evidence=("filename:template_keyword",),
            ),
        ),
        included_file_ids=[],
        total_chars=0,
        truncated=False,
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
async def test_runtime_planning_state_keeps_uploaded_file_roles_without_classifier() -> (
    None
):
    file_id = uuid4()
    attachment_context = AIBuilderAttachmentContext(
        context=None,
        discovery_context=None,
        evidence=(
            AIBuilderAttachmentEvidence(
                file_id=file_id,
                filename="lagstod.pdf",
                file_type=FileType.DOCUMENT,
                mimetype="application/pdf",
                has_readable_text=True,
                excerpt="Lagstöd som ska användas vid bedömning.",
                inferred_role="reference_material",
                role_confidence="medium",
                role_evidence=("filename:reference_keyword",),
            ),
        ),
        included_file_ids=[],
        total_chars=0,
        truncated=False,
    )

    state = await build_runtime_planning_state(
        [ConversationMessage(role="user", content="   ")],
        litellm_client=AsyncMock(),
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        attachment_context=attachment_context,
    )

    assert len(state.file_roles) == 1
    assert state.file_roles[0].file_id == file_id
    assert state.file_roles[0].role == "reference_material"


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
async def test_runtime_planning_state_passes_uploaded_file_evidence_to_classifier() -> (
    None
):
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps({"slots": [], "assumptions": [], "contradictions": []})
    )

    await build_runtime_planning_state(
        [
            ConversationMessage(
                role="user",
                content="Jag vill bygga ett transkriberingsflöde.",
                metadata={"ui_language": "sv"},
            )
        ],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        ui_language="sv",
        attachment_context=_attachment_context(),
    )

    messages = litellm_client.acompletion.await_args.kwargs["messages"]
    prompt = "\n".join(message["content"] for message in messages)
    assert "Unconfirmed uploaded-file evidence" in prompt
    assert "filename: beslutsmall.docx" in prompt
    assert "has_readable_text: false" in prompt


@pytest.mark.asyncio
async def test_uploaded_docx_evidence_alone_does_not_deterministically_resolve_terminal_output() -> (
    None
):
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps({"slots": [], "assumptions": [], "contradictions": []})
    )

    state = await build_runtime_planning_state(
        [
            ConversationMessage(
                role="user",
                content="Jag vill bygga ett transkriberingsflöde.",
                metadata={"ui_language": "sv"},
            )
        ],
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        ui_language="sv",
        attachment_context=_attachment_context(),
    )

    assert "terminal_output" not in state.resolved_slots


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
    assert "terminal_output" in question_ids
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


def test_targeted_bias_canonicalizes_legacy_question_id_to_slot() -> None:
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
    assert bias.asked_question_id == "terminal_output"
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
