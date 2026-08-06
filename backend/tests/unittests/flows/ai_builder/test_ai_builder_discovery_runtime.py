from __future__ import annotations

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.authentication.principal_types import PrincipalType
from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.completion_service import (
    ResolvedCompletionModelRoute,
)
from eneo.files.file_models import File, FileType
from eneo.flows.ai_builder import ai_builder_discovery_runtime as runtime
from eneo.flows.ai_builder import ai_builder_slot_classifier as classifier
from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AI_BUILDER_MAX_ATTACHMENTS,
    AIBuilderAttachmentContext,
    AIBuilderAttachmentContextPolicy,
    AIBuilderAttachmentEvidence,
    AIBuilderAttachmentSchemaDiscovery,
    build_ai_builder_attachment_context_for_model,
    render_ai_builder_attachment_evidence,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    SlotClassificationOutputSchemaFieldsMetadata,
    metadata_with_slot_classification,
    slot_classification_metadata_from_attempt,
)
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    create_compile_context_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_discovery import (
    analyze_discovery,
    build_discovery_block_message,
)
from eneo.flows.ai_builder.ai_builder_discovery_runtime import (
    _targeted_classification_bias,
    build_discovery_runtime_result,
    build_runtime_discovery_context,
    build_slot_classification_input,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_plan_proposal_task import (
    build_plan_proposal_system_prompt,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    SchemaDirectionSelection,
    build_declared_schema_candidate,
    build_schema_evidence,
)
from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    UNKNOWN_SLOT_VALUE,
    ClassifiedEvidence,
    ClassifiedFileRole,
    ClassifiedOutputSchemaFieldDelta,
    ClassifiedSchemaDirection,
    ClassifiedSlot,
    SlotClassificationAttempt,
    SlotClassificationInput,
    SlotClassificationResult,
    SlotClassificationSource,
    parse_slot_classification_response,
)
from eneo.flows.ai_builder.ai_builder_slot_classifier import (
    slot_classification_provider_identity,
)
from eneo.flows.ai_builder.ai_builder_turn_controller import (
    ConfirmRequirements,
    resolve_turn_control,
)
from eneo.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    CheckpointIntent,
    ExampleOutputCitation,
    ExampleOutputConstraintEvidence,
    ExampleOutputSourceCoverage,
    FileRoleEvidence,
    MappedFileLimit,
    PlanningState,
    ResolvedSlot,
)
from eneo.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
)
from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.flows.flow_review_policy import FlowStepReviewMode


def _make_response(content: object, *, complete_contract: bool = True) -> MagicMock:
    if complete_contract and isinstance(content, str):
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(payload, dict):
                content = json.dumps(
                    {
                        "slots": [],
                        "file_roles": [],
                        "checkpoint_updates": [],
                        "form_intake": None,
                        "output_schema_fields": None,
                        "example_output_constraints": None,
                        "schema_direction": None,
                        "secondary_obligations": [],
                        "assumptions": [],
                        "contradictions": [],
                        **payload,
                    }
                )
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _route(
    *,
    model: str = "gpt-test",
    provider_type: str = "openai",
    kwargs: dict[str, object] | None = None,
) -> ResolvedCompletionModelRoute:
    return ResolvedCompletionModelRoute(
        litellm_model=model,
        provider_type=provider_type,
        litellm_kwargs=kwargs or {},
        supported_model_kwargs=SupportedModelKwargs(
            temperature=ModelKwargCapability(supported=True)
        ),
    )


def _classification_input(
    conversation: list[ConversationMessage],
    attachment_context: AIBuilderAttachmentContext | None = None,
) -> SlotClassificationInput:
    return build_slot_classification_input(
        conversation,
        attachment_context,
    )


def _cited(quote: str, *, message_id: str = "user-1") -> dict[str, str]:
    return {"source_id": f"user_message:{message_id}", "quote": quote}


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
            "comparison_scope": _slot(
                "comparison_scope",
                "no_direct_compare",
            ),
            "runtime_metadata_fields": _slot(
                "runtime_metadata_fields",
                "no_extra_metadata",
            ),
        },
    )


@pytest.mark.asyncio
async def test_carried_commit_auto_accepts_the_mapped_limit_and_asks_real_gaps() -> (
    None
):
    persisted = PlanningState.empty()
    persisted.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "documents"),
        "terminal_output": _slot("terminal_output", "structured_text"),
        "document_material_scope": _slot(
            "document_material_scope",
            "multiple_documents_case",
        ),
    }
    draft = derive_architecture_commit_draft(persisted)
    assert draft is not None
    persisted.architecture_commit = finalize_architecture_commit(draft)
    persisted.mapped_file_limit = MappedFileLimit(
        proposed_value=8,
        diagnostic="confirmation_required",
    )

    result = await build_discovery_runtime_result(
        [
            ConversationMessage(
                role="user",
                content="documents",
                metadata={
                    "question_answer": {
                        "question_id": "primary_runtime_input",
                        "selected_option_id": "documents",
                        "selected_value": "documents",
                    }
                },
            ),
            ConversationMessage(
                role="user",
                content="structured text",
                metadata={
                    "question_answer": {
                        "question_id": "terminal_output",
                        "selected_option_id": "structured_text",
                        "selected_value": "structured_text",
                    }
                },
            ),
            ConversationMessage(
                role="user",
                content="multiple documents",
                metadata={
                    "question_answer": {
                        "question_id": "document_material_scope",
                        "selected_option_id": "multiple_documents_case",
                        "selected_value": "multiple_documents_case",
                    }
                },
            ),
        ],
        tenant_id=uuid4(),
        max_input_tokens=100_000,
        max_output_tokens=2_000,
        allow_classification=False,
        mapped_execution_policy=FlowMappedExecutionPolicy(
            max_provider_calls_per_mapped_step=8,
        ),
        persisted_planning_state=persisted,
        attached_file_ids=frozenset(),
    )

    assert result.planning_state.architecture_commit == persisted.architecture_commit
    # The shipped ceiling resolves silently; discovery spends the question
    # budget on a genuinely unresolved slot instead.
    assert "mapped_file_limit" not in result.discovery_analysis.selected_question_ids
    assert result.planning_state.mapped_file_limit.accepted_value == 7
    assert result.planning_state.mapped_file_limit.provenance == "policy_default"


def test_classifier_schema_direction_preserves_shape_and_assignment_evidence() -> None:
    candidate = build_declared_schema_candidate(
        {"type": "object", "properties": {"case_id": {"type": "string"}}},
        provenance=("message:user-1:fenced_json_schema",),
    )
    state = PlanningState.empty()

    runtime._apply_schema_direction(
        state,
        candidates=(candidate,),
        direction=ClassifiedSchemaDirection(
            candidate_fingerprints=(candidate.fingerprint,),
            input_fingerprint=candidate.fingerprint,
            output_fingerprint=None,
            reference_only=False,
            confidence="medium",
            reason="The user identifies the schema as runtime input.",
            evidence=(
                ClassifiedEvidence(
                    source_id="user_message:user-1",
                    quote="schema in intake.json is input",
                ),
            ),
        ),
    )

    assert state.input_schema_evidence is not None
    assert state.input_schema_evidence.confidence == "medium"
    assert state.input_schema_evidence.evidence == [
        "message:user-1:fenced_json_schema",
        "quote:user_message:user-1:schema in intake.json is input",
    ]


def test_structured_schema_direction_preserves_exact_answer_trace() -> None:
    candidate = build_declared_schema_candidate(
        {"type": "object", "properties": {"result": {"type": "string"}}},
        provenance=(
            "file:00000000-0000-0000-0000-000000000001:json_schema_attachment",
        ),
    )
    state = PlanningState.empty()
    selected_token = f"output:{candidate.fingerprint}"

    runtime._apply_schema_direction(
        state,
        candidates=(candidate,),
        direction=SchemaDirectionSelection(
            candidate_fingerprints=(candidate.fingerprint,),
            input_fingerprint=None,
            output_fingerprint=candidate.fingerprint,
            reference_only=False,
            confidence="high",
            evidence=(f"quote:structured_answer:user-2:0:{selected_token}",),
        ),
    )

    assert state.output_schema_evidence is not None
    assert state.output_schema_evidence.confidence == "high"
    assert state.output_schema_evidence.evidence == [
        "file:00000000-0000-0000-0000-000000000001:json_schema_attachment",
        f"quote:structured_answer:user-2:0:{selected_token}",
    ]


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
                coverage="inventory_only",
                inferred_role="template",
                role_confidence="medium",
                role_evidence=("content:template_placeholder:kundnamn",),
            ),
        ),
        included_file_ids=[],
        total_chars=0,
        truncated=False,
    )


def test_slot_classification_input_preserves_typed_source_chronology() -> None:
    first_file_id = uuid4()
    second_file_id = uuid4()
    conversation = [
        ConversationMessage(
            message_id="user-1",
            role="user",
            content="Behåll OriginalCase i rapporten.",
        ),
        ConversationMessage(
            message_id="assistant-1",
            role="assistant",
            content="Vilket format?",
            metadata={"question_id": "terminal_output"},
        ),
        ConversationMessage(
            message_id="user-2",
            role="user",
            content="docx_document",
            metadata={
                "question_answer": {
                    "question_id": "terminal_output",
                    "selected_value": "docx_document",
                }
            },
        ),
        ConversationMessage(
            message_id="tool-1",
            role="tool",
            content="internal planner prose",
        ),
    ]
    attachment_context = AIBuilderAttachmentContext(
        context=None,
        evidence=tuple(
            AIBuilderAttachmentEvidence(
                file_id=file_id,
                filename=filename,
                file_type=FileType.DOCUMENT,
                mimetype="application/pdf",
                has_readable_text=True,
                excerpt=excerpt,
                coverage="fully_seen",
            )
            for file_id, filename, excerpt in (
                (second_file_id, "second.pdf", "SECOND"),
                (first_file_id, "first.pdf", "FIRST"),
            )
        ),
        included_file_ids=[],
        total_chars=0,
        truncated=False,
    )

    classification_input = _classification_input(
        conversation,
        attachment_context,
    )

    assert classification_input.sources[0].source_id == "user_message:user-1"
    assert classification_input.current_user_message_id == "user-2"
    assert classification_input.sources[0].text == "Behåll OriginalCase i rapporten."
    assert classification_input.sources[1].source_id == "structured_answer:user-2:0"
    assert classification_input.sources[1].question_id == "terminal_output"
    assert classification_input.sources[1].selected_value == "docx_document"
    assert [source.file_id for source in classification_input.sources[2:]] == sorted(
        (first_file_id, second_file_id),
        key=str,
    )
    assert all(
        "internal planner prose" not in source.text
        for source in classification_input.sources
    )


def test_blank_current_turn_cannot_readmit_prior_named_json_fields() -> None:
    classification_input = _classification_input(
        [
            ConversationMessage(
                message_id="user-prior",
                role="user",
                content="JSON-resultatet ska innehålla sökta insatser.",
            ),
            ConversationMessage(
                message_id="user-current",
                role="user",
                content="   ",
            ),
        ],
        None,
    )

    result = parse_slot_classification_response(
        json.dumps(
            {
                "slots": [],
                "file_roles": [],
                "checkpoint_updates": [],
                "form_intake": None,
                "output_schema_fields": {
                    "operation": "update",
                    "field_names": ["sökta insatser"],
                    "removed_field_names": [],
                    "confidence": "high",
                    "reason": "The earlier turn named the field.",
                    "evidence": [
                        {
                            "source_id": "user_message:user-prior",
                            "quote": "sökta insatser",
                        }
                    ],
                },
                "example_output_constraints": None,
                "schema_direction": None,
                "secondary_obligations": [],
                "assumptions": [],
                "contradictions": [],
            }
        ),
        allowed_slot_values={},
        classification_input=classification_input,
    )

    assert classification_input.current_user_message_id == "user-current"
    assert result is not None
    assert result.output_schema_fields is None


def test_slot_classification_input_rejects_attachment_inventory_over_limit() -> None:
    attachment_context = AIBuilderAttachmentContext(
        context=None,
        evidence=tuple(
            AIBuilderAttachmentEvidence(
                file_id=uuid4(),
                filename=f"source-{index}.txt",
                file_type=FileType.TEXT,
                mimetype="text/plain",
                has_readable_text=True,
                excerpt="evidence",
                coverage="fully_seen",
            )
            for index in range(AI_BUILDER_MAX_ATTACHMENTS + 1)
        ),
        included_file_ids=[],
        total_chars=0,
        truncated=False,
    )

    with pytest.raises(AIBuilderBadRequestException) as error:
        _classification_input([], attachment_context)

    assert error.value.code is AIBuilderErrorCode.BAD_REQUEST
    assert str(AI_BUILDER_MAX_ATTACHMENTS) in str(error.value)


def test_slot_classification_input_preserves_selected_option_only_answer() -> None:
    classification_input = _classification_input(
        [
            ConversationMessage(
                message_id="user-option",
                role="user",
                content="docx_document",
                metadata={
                    "question_answer": {
                        "question_id": "terminal_output",
                        "selected_option_id": "docx_document",
                    }
                },
            )
        ],
        None,
    )

    assert [source.source_id for source in classification_input.sources] == [
        "structured_answer:user-option:0"
    ]
    source = classification_input.sources[0]
    assert source.question_id == "terminal_output"
    assert source.selected_value == "docx_document"
    assert source.text == "docx_document"


def test_slot_classification_input_carries_each_answering_question_identity() -> None:
    classification_input = _classification_input(
        [
            ConversationMessage(
                message_id="assistant-input",
                role="assistant",
                content="Vilket underlag?",
                metadata={"question_id": "primary_runtime_input"},
            ),
            ConversationMessage(
                message_id="user-input",
                role="user",
                content="Flera dokument per ärende.",
            ),
            ConversationMessage(
                message_id="assistant-output",
                role="assistant",
                content="Vilket slutformat?",
                metadata={"question_id": "terminal_output"},
            ),
            ConversationMessage(
                message_id="tool-between",
                role="tool",
                content="internal tool output",
            ),
            ConversationMessage(
                message_id="user-output",
                role="user",
                content="En fil jag kan ladda ner.",
            ),
        ],
        None,
    )

    assert [
        (source.source_id, source.question_id)
        for source in classification_input.sources
    ] == [
        ("user_message:user-input", "primary_runtime_input"),
        ("user_message:user-output", "terminal_output"),
    ]


@pytest.mark.asyncio
async def test_runtime_fills_reserved_conversation_capacity() -> None:
    long_text = ("alpha beta gamma delta " * 3_000)[:50_000]
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(json.dumps({}))

    context = await build_runtime_discovery_context(
        [
            ConversationMessage(
                message_id="user-1",
                role="user",
                content=long_text,
            )
        ],
        litellm_client=litellm_client,
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=16_000,
        max_output_tokens=1_000,
        safety_buffer_tokens=1_000,
        minimum_conversation_tokens=4_000,
    )

    litellm_client.acompletion.assert_awaited_once()
    provider_request = litellm_client.acompletion.await_args.kwargs
    user_prompt = provider_request["messages"][1]["content"]
    admitted_text = user_prompt.split(
        "Typed evidence sources in conversation chronology, followed by stable "
        "file-id order:\n",
        1,
    )[1].split("\n\nUnresolved slots and allowed values:", 1)[0]
    admitted_text = admitted_text.split("\n", 1)[1]
    assert 49_000 <= len(admitted_text) < len(long_text)
    assert classifier.slot_classification_request_fits_model(
        messages=provider_request["messages"],
        response_format=provider_request["response_format"],
        litellm_model="gpt-test",
        max_input_tokens=16_000,
        max_output_tokens=1_000,
        safety_buffer_tokens=1_000,
    )
    assert context.slot_classification_metadata is not None
    assert [
        item.truncated for item in context.slot_classification_metadata.source_inventory
    ] == [True]


def test_slot_classification_input_keeps_parser_shape_invariants() -> None:
    conversation = [
        ConversationMessage(
            message_id=f"user-{index}",
            role="user",
            content=f"message-{index}",
        )
        for index in range(120)
    ]
    conversation.append(
        ConversationMessage(
            message_id="user-latest",
            role="user",
            content="latest-message",
        )
    )

    classification_input = _classification_input(conversation)
    structured_source = runtime._bound_classification_transcript(
        [
            SlotClassificationSource(
                source_id="structured_answer:user-answer:0",
                kind="structured_answer",
                text="X" * 600,
                message_id="user-answer",
                question_id="terminal_output",
                selected_value="X" * 600,
            )
        ]
    )[0]

    assert len(classification_input.sources) == 120
    assert classification_input.sources[0].source_id == "user_message:user-1"
    assert classification_input.sources[-1].source_id == "user_message:user-latest"
    assert structured_source.source_id == "structured_answer:user-answer:0"
    assert len(structured_source.text) == 500
    assert structured_source.selected_value == structured_source.text
    assert structured_source.truncated is True


def test_discovery_analysis_carries_classifier_assumptions() -> None:
    analysis = analyze_discovery(
        [ConversationMessage(role="user", content="Build a document summary flow.")],
        planning_state=_resolved_state(),
        slot_classification_result=SlotClassificationResult(
            assumptions=("The output can be a short summary.",)
        ),
    )

    assert analysis.assumptions == ("The output can be a short summary.",)


@pytest.mark.asyncio
async def test_runtime_planning_state_classifies_current_turn_when_slots_are_strong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(json.dumps({}))
    monkeypatch.setattr(
        runtime,
        "build_planning_state_from_conversation",
        lambda *_args, **_kwargs: _resolved_state(),
    )

    state = (
        await build_runtime_discovery_context(
            [ConversationMessage(role="user", content="Skapa ett komplett flöde.")],
            litellm_client=litellm_client,
            completion_model_route=_route(),
            tenant_id=uuid4(),
            max_input_tokens=100_000,
            max_output_tokens=2_000,
        )
    ).planning_state

    assert state.resolved_slots["primary_runtime_input"].value == "text"
    assert state.checkpoint_intents == []
    litellm_client.acompletion.assert_awaited_once()


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
                        "value": "basic_runtime_metadata",
                        "confidence": "high",
                        "reason": "runtime fields requested",
                        "evidence": [
                            _cited("Användaren ska ange målgrupp och detaljnivå")
                        ],
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

    state = (
        await build_runtime_discovery_context(
            [
                ConversationMessage(
                    message_id="user-1",
                    role="user",
                    content="Användaren ska ange målgrupp och detaljnivå vid körning.",
                )
            ],
            litellm_client=litellm_client,
            completion_model_route=_route(),
            tenant_id=uuid4(),
            max_input_tokens=100_000,
            max_output_tokens=2_000,
        )
    ).planning_state

    assert state.resolved_slots["runtime_metadata_fields"].source == "model"
    assert (
        state.resolved_slots["runtime_metadata_fields"].value
        == "basic_runtime_metadata"
    )


@pytest.mark.asyncio
async def test_runtime_planning_state_skips_model_when_freeform_text_is_empty() -> None:
    litellm_client = AsyncMock()

    await build_runtime_discovery_context(
        [ConversationMessage(role="user", content="   ")],
        litellm_client=litellm_client,
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=100_000,
        max_output_tokens=2_000,
    )

    litellm_client.acompletion.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_planning_state_keeps_uploaded_file_roles_without_classifier() -> (
    None
):
    file_id = uuid4()
    attachment_context = AIBuilderAttachmentContext(
        context=None,
        evidence=(
            AIBuilderAttachmentEvidence(
                file_id=file_id,
                filename="lagstod.pdf",
                file_type=FileType.DOCUMENT,
                mimetype="application/pdf",
                has_readable_text=True,
                excerpt="Fyll i {{ kundnamn }}.",
                coverage="fully_seen",
                inferred_role="template",
                role_confidence="medium",
                role_evidence=("content:template_placeholder:kundnamn",),
            ),
        ),
        included_file_ids=[],
        total_chars=0,
        truncated=False,
    )

    state = (
        await build_runtime_discovery_context(
            [ConversationMessage(role="user", content="   ")],
            litellm_client=AsyncMock(),
            completion_model_route=_route(),
            tenant_id=uuid4(),
            max_input_tokens=100_000,
            max_output_tokens=2_000,
            attachment_context=attachment_context,
        )
    ).planning_state

    assert len(state.file_roles) == 1
    assert state.file_roles[0].file_id == file_id
    assert state.file_roles[0].role == "template"


@pytest.mark.asyncio
async def test_degraded_turn_replays_semantic_role_over_fresh_attachment_facts() -> (
    None
):
    file_id = uuid4()
    user_source_id = "user_message:file-role"
    classification_input = SlotClassificationInput(
        sources=(
            SlotClassificationSource(
                source_id=user_source_id,
                kind="user_message",
                text="This attachment is the example output.",
                message_id="file-role",
            ),
            SlotClassificationSource(
                source_id=f"uploaded_file:{file_id}",
                kind="uploaded_file",
                text="filename: earlier-example.pdf",
                file_id=file_id,
                coverage="fully_seen",
            ),
        )
    )
    result = SlotClassificationResult(
        file_roles=(
            ClassifiedFileRole(
                file_id=file_id,
                role="example_output",
                confidence="high",
                reason="The user identified the example output.",
                evidence=(
                    ClassifiedEvidence(
                        source_id=user_source_id,
                        quote="This attachment is the example output.",
                    ),
                ),
            ),
        )
    )
    classification = slot_classification_metadata_from_attempt(
        SlotClassificationAttempt(outcome="resolved", result=result),
        prompt_hash="a" * 64,
        classification_input=classification_input,
        model="openai/gpt-test",
        provider="openai",
    )
    assert classification is not None
    conversation_metadata = metadata_with_slot_classification(None, classification)
    assert conversation_metadata is not None

    state = (
        await build_runtime_discovery_context(
            [
                ConversationMessage(
                    message_id="file-role",
                    role="user",
                    content="This attachment is the example output.",
                    metadata=conversation_metadata,
                )
            ],
            tenant_id=uuid4(),
            max_input_tokens=100_000,
            max_output_tokens=2_000,
            allow_classification=False,
            attachment_context=AIBuilderAttachmentContext(
                context=None,
                evidence=(
                    AIBuilderAttachmentEvidence(
                        file_id=file_id,
                        filename="refreshed-example.pdf",
                        file_type=FileType.DOCUMENT,
                        mimetype="application/pdf",
                        has_readable_text=True,
                        excerpt="Only the refreshed excerpt is available.",
                        coverage="excerpt_truncated",
                        inferred_role="context_only",
                        role_confidence="low",
                        role_evidence=("fallback:unclassified_file",),
                    ),
                ),
                included_file_ids=[file_id],
                total_chars=39,
                truncated=True,
            ),
        )
    ).planning_state

    assert len(state.file_roles) == 1
    role = state.file_roles[0]
    assert role.filename == "refreshed-example.pdf"
    assert role.has_readable_text is True
    assert role.coverage == "excerpt_truncated"
    assert role.role == "example_output"
    assert role.source == "model"
    assert role.confidence == "high"


@pytest.mark.asyncio
async def test_runtime_planning_state_uses_structural_template_for_docx_mode() -> None:
    file_id = uuid4()
    conversation = [
        ConversationMessage(
            role="user",
            content="Jag vill bygga ett flöde som ger en Word-fil i slutet.",
            metadata={"ui_language": "sv"},
        )
    ]

    state = (
        await build_runtime_discovery_context(
            conversation,
            litellm_client=AsyncMock(),
            completion_model_route=_route(),
            tenant_id=uuid4(),
            max_input_tokens=100_000,
            max_output_tokens=2_000,
            ui_language="sv",
            allow_classification=False,
            attachment_context=AIBuilderAttachmentContext(
                context=None,
                evidence=(
                    AIBuilderAttachmentEvidence(
                        file_id=file_id,
                        filename="mall.docx",
                        file_type=FileType.DOCUMENT,
                        mimetype=(
                            "application/vnd.openxmlformats-officedocument."
                            "wordprocessingml.document"
                        ),
                        has_readable_text=True,
                        excerpt="Fyll i {{ kundnamn }}.",
                        coverage="fully_seen",
                        inferred_role="template",
                        role_confidence="medium",
                        role_evidence=("content:template_placeholder:kundnamn",),
                    ),
                ),
                included_file_ids=[],
                total_chars=0,
                truncated=False,
                output_schema_evidence=build_schema_evidence(
                    json_schema={
                        "type": "object",
                        "properties": {"kundnamn": {"type": "string"}},
                    },
                    source="template_placeholders",
                    source_file_ids=(file_id,),
                    confidence="high",
                    evidence=[
                        f"file:{file_id}:template_placeholder_source",
                        f"file:{file_id}:content:template_placeholder:kundnamn",
                    ],
                    total_count=1,
                    truncated=False,
                ),
            ),
        )
    ).planning_state

    slot = state.resolved_slots["docx_output_mode"]
    assert slot.value == "template_fill_docx"
    assert slot.source == "attachment_structure"
    assert slot.confidence == "high"
    assert slot.evidence == [f"file:{file_id}:content:template_placeholder:kundnamn"]
    evidence = state.output_schema_evidence
    assert evidence is not None
    assert evidence.source == "template_placeholders"
    assert evidence.confidence == "high"
    assert evidence.evidence == [
        f"file:{file_id}:template_placeholder_source",
        f"file:{file_id}:content:template_placeholder:kundnamn",
    ]
    properties = evidence.json_schema["properties"]
    assert isinstance(properties, dict)
    assert list(properties) == ["kundnamn"]

    analysis = analyze_discovery(conversation, planning_state=state)
    assert "docx_output_mode" not in analysis.selected_question_ids


@pytest.mark.asyncio
async def test_runtime_retains_attachment_schema_as_unassigned_candidate() -> None:
    file_id = uuid4()
    candidate = build_declared_schema_candidate(
        {"type": "object", "properties": {"decision": {"type": "string"}}},
        source_file_ids=(file_id,),
        provenance=(f"file:{file_id}:json_schema_attachment",),
    )

    context = await build_runtime_discovery_context(
        [],
        tenant_id=uuid4(),
        max_input_tokens=100_000,
        max_output_tokens=2_000,
        allow_classification=False,
        attachment_context=AIBuilderAttachmentContext(
            context=None,
            evidence=(),
            included_file_ids=[],
            total_chars=0,
            truncated=False,
            schema_discovery=AIBuilderAttachmentSchemaDiscovery(
                candidates=(candidate,)
            ),
        ),
    )

    assert context.schema_candidates == (candidate,)
    assert context.schema_direction_pending is True
    assert context.planning_state.input_schema_evidence is None
    assert context.planning_state.output_schema_evidence is None
    assert "terminal_output" not in context.planning_state.resolved_slots


@pytest.mark.asyncio
async def test_runtime_input_schema_does_not_override_requested_docx_output() -> None:
    file_id = uuid4()
    candidate = build_declared_schema_candidate(
        {
            "type": "object",
            "properties": {"case_id": {"type": "string"}},
            "required": ["case_id"],
        },
        source_file_ids=(file_id,),
        provenance=(f"file:{file_id}:json_schema_attachment",),
    )
    quote = "Det bifogade JSON-schemat validerar indata vid körning."
    conversation = [
        ConversationMessage(
            message_id="user-1",
            role="user",
            content=(
                f"{quote} "
                "Bygg ett flöde som tar emot JSON vid körning och genererar "
                "en DOCX-rapport utan mall."
            ),
        )
    ]
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [],
                "schema_direction": {
                    "input_fingerprint": candidate.fingerprint,
                    "output_fingerprint": None,
                    "reference_only": False,
                    "confidence": "medium",
                    "reason": "The user identifies this as runtime input.",
                    "evidence": [_cited(quote)],
                },
            }
        )
    )

    context = await build_runtime_discovery_context(
        conversation,
        litellm_client=litellm_client,
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=100_000,
        max_output_tokens=2_000,
        attachment_context=AIBuilderAttachmentContext(
            context=None,
            evidence=(),
            included_file_ids=[],
            total_chars=0,
            truncated=False,
            schema_discovery=AIBuilderAttachmentSchemaDiscovery(
                candidates=(candidate,)
            ),
        ),
    )
    state = context.planning_state

    assert context.schema_direction_pending is False
    assert state.input_schema_evidence is not None
    assert state.input_schema_evidence.fingerprint == candidate.fingerprint
    assert state.input_schema_evidence.confidence == "medium"
    assert state.output_schema_evidence is None
    assert state.resolved_slots["terminal_output"].value == "docx_document"
    assert state.resolved_slots["docx_output_mode"].value == "generated_docx"
    analysis = analyze_discovery(conversation, planning_state=state)
    assert "terminal_output" not in analysis.selected_question_ids
    compile_context = create_compile_context_from_planning_state(state)
    assert compile_context is not None
    assert compile_context.final_output_type is None
    assert compile_context.terminal_output_schema is None


@pytest.mark.asyncio
async def test_attachment_only_direction_citation_does_not_assign_schema() -> None:
    file_id = uuid4()
    excerpt = '{"case_id":"123"}'
    candidate = build_declared_schema_candidate(
        {
            "type": "object",
            "properties": {"case_id": {"type": "string"}},
            "required": ["case_id"],
        },
        source_file_ids=(file_id,),
        provenance=(f"file:{file_id}:json_schema_attachment",),
    )
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [],
                "schema_direction": {
                    "input_fingerprint": candidate.fingerprint,
                    "output_fingerprint": None,
                    "reference_only": False,
                    "confidence": "medium",
                    "reason": "The upload contains JSON.",
                    "evidence": [
                        {
                            "source_id": f"uploaded_file:{file_id}",
                            "quote": excerpt,
                        }
                    ],
                },
            }
        )
    )

    context = await build_runtime_discovery_context(
        [
            ConversationMessage(
                message_id="user-1",
                role="user",
                content="Generate a DOCX report without a template.",
            )
        ],
        litellm_client=litellm_client,
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=100_000,
        max_output_tokens=2_000,
        attachment_context=AIBuilderAttachmentContext(
            context=excerpt,
            evidence=(
                AIBuilderAttachmentEvidence(
                    file_id=file_id,
                    filename="runtime-input.schema.json",
                    file_type=FileType.TEXT,
                    mimetype="application/json",
                    has_readable_text=True,
                    excerpt=excerpt,
                    coverage="fully_seen",
                ),
            ),
            included_file_ids=[file_id],
            total_chars=len(excerpt),
            truncated=False,
            schema_discovery=AIBuilderAttachmentSchemaDiscovery(
                candidates=(candidate,)
            ),
        ),
    )
    state = context.planning_state

    assert state.resolved_slots["terminal_output"].value == "docx_document"
    assert state.resolved_slots["docx_output_mode"].value == "generated_docx"
    assert state.input_schema_evidence is None
    assert state.output_schema_evidence is None
    assert context.schema_direction_pending is True
    assert context.slot_classification_result is not None
    assert context.slot_classification_result.slots == ()
    assert context.slot_classification_result.schema_direction is not None
    assert context.slot_classification_result.schema_direction.confidence == "low"
    assert context.slot_classification_metadata is not None
    assert context.slot_classification_metadata.slots == []
    litellm_client.acompletion.assert_awaited_once()


@pytest.mark.asyncio
async def test_runtime_does_not_treat_template_placeholders_as_json_terminal() -> None:
    file_id = uuid4()
    template_evidence = build_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {"kundnamn": {"type": "string"}},
        },
        source="template_placeholders",
        source_file_ids=(file_id,),
        confidence="high",
        evidence=[
            f"file:{file_id}:template_placeholder_source",
            f"file:{file_id}:content:template_placeholder:kundnamn",
        ],
        total_count=1,
        truncated=False,
    )

    state = (
        await build_runtime_discovery_context(
            [
                ConversationMessage(
                    role="user", content="Bygg ett flöde för våra handlingar."
                )
            ],
            tenant_id=uuid4(),
            max_input_tokens=100_000,
            max_output_tokens=2_000,
            allow_classification=False,
            attachment_context=AIBuilderAttachmentContext(
                context=None,
                evidence=(),
                included_file_ids=[],
                total_chars=0,
                truncated=False,
                output_schema_evidence=template_evidence,
            ),
        )
    ).planning_state

    assert state.output_schema_evidence == template_evidence
    assert "terminal_output" not in state.resolved_slots


@pytest.mark.asyncio
async def test_runtime_infers_schema_only_after_example_output_classification() -> None:
    file_id = uuid4()
    source_id = f"uploaded_file:{file_id}"
    exact_json = '{"decision":"approved","count":2}'
    evidence = (
        ClassifiedEvidence(
            source_id=source_id,
            quote=exact_json,
        ),
    )
    classification_result = SlotClassificationResult(
        file_roles=(
            ClassifiedFileRole(
                file_id=file_id,
                role="example_output",
                confidence="medium",
                reason="The user identifies this upload as the expected result.",
                evidence=evidence,
            ),
        ),
        example_output_constraints=ExampleOutputConstraintEvidence(
            source_file_ids=[file_id],
            source_coverage=[
                ExampleOutputSourceCoverage(
                    file_id=file_id,
                    coverage="fully_seen",
                )
            ],
            headings=["Decision"],
            confidence="medium",
            citations=[
                ExampleOutputCitation(
                    source_id=source_id,
                    file_id=file_id,
                    quote=exact_json,
                )
            ],
        ),
    )
    attachment_context = AIBuilderAttachmentContext(
        context=exact_json,
        evidence=(
            AIBuilderAttachmentEvidence(
                file_id=file_id,
                filename="expected.json",
                file_type=FileType.TEXT,
                mimetype="application/json",
                has_readable_text=True,
                excerpt=exact_json,
                coverage="fully_seen",
            ),
        ),
        included_file_ids=[file_id],
        total_chars=len(exact_json),
        truncated=False,
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        classify = AsyncMock(
            return_value=SlotClassificationAttempt("resolved", classification_result)
        )
        monkeypatch.setattr(runtime, "classify_slots", classify)
        state = (
            await build_runtime_discovery_context(
                [ConversationMessage(role="user", content="Use the attached example.")],
                litellm_client=AsyncMock(),
                completion_model_route=_route(),
                tenant_id=uuid4(),
                max_input_tokens=100_000,
                max_output_tokens=2_000,
                attachment_context=attachment_context,
            )
        ).planning_state

    assert state.example_output_constraints is not None
    assert state.example_output_schema_inference is not None
    assert state.example_output_schema_inference.status == "inferred"
    assert state.output_schema_evidence is not None
    assert state.output_schema_evidence.source == "inferred_example"
    assert state.output_schema_evidence.json_schema == {
        "type": "object",
        "properties": {
            "decision": {"type": "string"},
            "count": {"type": "integer"},
        },
    }


@pytest.mark.asyncio
async def test_runtime_records_incomplete_example_json_without_guessing_schema() -> (
    None
):
    file_id = uuid4()
    source_id = f"uploaded_file:{file_id}"
    excerpt = '{"decision":"approved"'
    classification_result = SlotClassificationResult(
        file_roles=(
            ClassifiedFileRole(
                file_id=file_id,
                role="example_output",
                confidence="medium",
                reason="The user identifies this upload as the expected result.",
                evidence=(
                    ClassifiedEvidence(
                        source_id=source_id,
                        quote=excerpt,
                    ),
                ),
            ),
        ),
        example_output_constraints=ExampleOutputConstraintEvidence(
            source_file_ids=[file_id],
            source_coverage=[
                ExampleOutputSourceCoverage(
                    file_id=file_id,
                    coverage="excerpt_truncated",
                )
            ],
            headings=["Decision"],
            confidence="medium",
            citations=[
                ExampleOutputCitation(
                    source_id=source_id,
                    file_id=file_id,
                    quote=excerpt,
                )
            ],
        ),
    )
    attachment_context = AIBuilderAttachmentContext(
        context=excerpt,
        evidence=(
            AIBuilderAttachmentEvidence(
                file_id=file_id,
                filename="expected.json",
                file_type=FileType.TEXT,
                mimetype="application/json",
                has_readable_text=True,
                excerpt=excerpt,
                coverage="excerpt_truncated",
            ),
        ),
        included_file_ids=[file_id],
        total_chars=len(excerpt),
        truncated=True,
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            runtime,
            "classify_slots",
            AsyncMock(
                return_value=SlotClassificationAttempt(
                    "resolved", classification_result
                )
            ),
        )
        state = (
            await build_runtime_discovery_context(
                [ConversationMessage(role="user", content="Use the attached example.")],
                litellm_client=AsyncMock(),
                completion_model_route=_route(),
                tenant_id=uuid4(),
                max_input_tokens=100_000,
                max_output_tokens=2_000,
                attachment_context=attachment_context,
            )
        ).planning_state

    assert state.output_schema_evidence is None
    assert state.example_output_schema_inference is not None
    assert state.example_output_schema_inference.status == "not_inferred"
    assert state.example_output_schema_inference.reason == "incomplete_content"


@pytest.mark.asyncio
async def test_runtime_planning_state_skips_model_when_classification_is_disabled() -> (
    None
):
    litellm_client = AsyncMock()

    await build_runtime_discovery_context(
        [ConversationMessage(role="user", content="Bygg ett sammanfattningsflöde.")],
        litellm_client=litellm_client,
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=100_000,
        max_output_tokens=2_000,
        allow_classification=False,
    )

    litellm_client.acompletion.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_records_skipped_context_budget_when_minimum_request_cannot_fit() -> (
    None
):
    litellm_client = AsyncMock()

    context = await build_runtime_discovery_context(
        [
            ConversationMessage(
                message_id="user-1",
                role="user",
                content="B",
            )
        ],
        litellm_client=litellm_client,
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=100,
        max_output_tokens=70,
        safety_buffer_tokens=20,
        minimum_conversation_tokens=10,
    )

    assert context.slot_classification_metadata is not None
    assert context.slot_classification_metadata.outcome == "skipped_context_budget"
    assert context.slot_classification_metadata.prompt_hash is None
    assert context.slot_classification_metadata.source_inventory[0].source_id == (
        "user_message:user-1"
    )
    assert context.slot_classification_metadata.source_inventory[0].source_sha256 == (
        hashlib.sha256(b"B").hexdigest()
    )
    assert context.slot_classification_metadata.source_inventory[0].truncated is False
    litellm_client.acompletion.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_refits_saturated_attachment_before_admitting_transcript() -> (
    None
):
    attachment = File(
        id=uuid4(),
        name="evidence.txt",
        checksum="checksum",
        size=200_000,
        mimetype="text/plain",
        file_type=FileType.TEXT,
        text="attachment evidence " * 10_000,
        owner_type=PrincipalType.USER,
        owner_user_id=uuid4(),
        tenant_id=uuid4(),
    )
    attachment_context = build_ai_builder_attachment_context_for_model(
        [attachment],
        policy=AIBuilderAttachmentContextPolicy(),
        model_name="gpt-test",
        max_input_tokens=16_000,
        max_output_tokens=1_000,
        safety_buffer_tokens=1_000,
        minimum_conversation_tokens=4_000,
    )
    assert attachment_context is not None
    original_uploaded_text = render_ai_builder_attachment_evidence(
        attachment_context.evidence[0]
    )
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(json.dumps({}))

    context = await build_runtime_discovery_context(
        [
            ConversationMessage(
                message_id="user-1",
                role="user",
                content="Summarize the attached evidence.",
            )
        ],
        litellm_client=litellm_client,
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=16_000,
        max_output_tokens=1_000,
        safety_buffer_tokens=1_000,
        minimum_conversation_tokens=4_000,
        attachment_context=attachment_context,
    )

    provider_request = litellm_client.acompletion.await_args.kwargs
    assert classifier.slot_classification_request_fits_model(
        messages=provider_request["messages"],
        response_format=provider_request["response_format"],
        litellm_model="gpt-test",
        max_input_tokens=16_000,
        max_output_tokens=1_000,
        safety_buffer_tokens=1_000,
    )
    assert context.slot_classification_metadata is not None
    assert [
        source.kind for source in context.slot_classification_metadata.source_inventory
    ] == ["user_message", "uploaded_file"]
    uploaded_inventory = context.slot_classification_metadata.source_inventory[1]
    assert (
        uploaded_inventory.source_sha256
        != hashlib.sha256(original_uploaded_text.encode("utf-8")).hexdigest()
    )
    assert uploaded_inventory.coverage == "excerpt_truncated"
    assert uploaded_inventory.truncated is True


@pytest.mark.asyncio
async def test_runtime_persists_exact_admitted_source_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admitted_input: SlotClassificationInput | None = None

    async def capture_classification_input(
        **kwargs: object,
    ) -> SlotClassificationAttempt:
        nonlocal admitted_input
        candidate = kwargs["classification_input"]
        assert isinstance(candidate, SlotClassificationInput)
        admitted_input = candidate
        return SlotClassificationAttempt(
            outcome="resolved", result=SlotClassificationResult()
        )

    monkeypatch.setattr(runtime, "classify_slots", capture_classification_input)
    context = await build_runtime_discovery_context(
        [
            ConversationMessage(
                message_id="user-old",
                role="user",
                content="old:" + "alpha beta gamma delta " * 1_500,
            ),
            ConversationMessage(
                message_id="user-latest",
                role="user",
                content="latest:" + "epsilon zeta eta theta " * 1_500,
            ),
        ],
        litellm_client=AsyncMock(),
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=12_000,
        max_output_tokens=1_000,
        safety_buffer_tokens=200,
        minimum_conversation_tokens=500,
    )

    assert admitted_input is not None
    assert context.slot_classification_metadata is not None
    persisted = context.slot_classification_metadata.source_inventory
    assert [item.source_id for item in persisted] == [
        source.source_id for source in admitted_input.sources
    ]
    assert [item.source_sha256 for item in persisted] == [
        hashlib.sha256(source.text.encode("utf-8")).hexdigest()
        for source in admitted_input.sources
    ]
    assert [item.truncated for item in persisted] == [
        source.truncated for source in admitted_input.sources
    ]


@pytest.mark.parametrize(
    ("provider_content", "expected_outcome", "expected_mutation"),
    [
        ({}, "resolved", False),
        (
            {
                "slots": [
                    {
                        "slot_name": "primary_runtime_input",
                        "value": "text",
                        "confidence": "high",
                        "reason": "The user supplied plain text.",
                        "evidence": [_cited("plain text")],
                        "evidence_level": "explicit",
                    }
                ]
            },
            "resolved",
            True,
        ),
        ("   ", "no_content", False),
        ("{not-json", "parse_failed", False),
        ([{"unexpected": "content"}], "parse_failed", False),
        (json.dumps({"slots": []}), "parse_failed", False),
    ],
    ids=[
        "valid-empty",
        "resolved-fact",
        "blank",
        "malformed",
        "non-string",
        "invalid-top-level-contract",
    ],
)
@pytest.mark.asyncio
async def test_runtime_persists_classifier_attempt_outcomes_before_state_mutation(
    monkeypatch: pytest.MonkeyPatch,
    provider_content: dict[str, object] | str | list[object] | None,
    expected_outcome: str,
    expected_mutation: bool,
) -> None:
    litellm_client = AsyncMock()
    if isinstance(provider_content, dict):
        litellm_client.acompletion.return_value = _make_response(
            json.dumps(provider_content)
        )
    elif provider_content is not None:
        litellm_client.acompletion.return_value = _make_response(
            provider_content, complete_contract=False
        )

    context = await build_runtime_discovery_context(
        [
            ConversationMessage(
                message_id="user-1",
                role="user",
                content=f"plain text {expected_outcome} {expected_mutation}",
            )
        ],
        litellm_client=litellm_client,
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=100_000,
        max_output_tokens=2_000,
    )

    assert context.slot_classification_metadata is not None
    assert context.slot_classification_metadata.outcome == expected_outcome
    assert (context.slot_classification_result is not None) == (
        expected_outcome == "resolved"
    )
    expected_primary_input = expected_mutation
    assert (
        context.planning_state.resolved_slots.get("primary_runtime_input") is not None
    ) == expected_primary_input
    if expected_mutation:
        assert (
            context.planning_state.resolved_slots["primary_runtime_input"].source
            == "model"
        )
    litellm_client.acompletion.assert_awaited_once()
    assert context.slot_classification_metadata.prompt_hash is not None


@pytest.mark.parametrize(
    ("operation", "prompt", "expected_mode"),
    [
        (
            "update",
            "Let me edit the report before delivery.",
            FlowStepReviewMode.EDIT,
        ),
        (
            "clear",
            "Do not pause for report approval anymore.",
            None,
        ),
    ],
)
@pytest.mark.asyncio
async def test_resolved_session_classifies_current_checkpoint_change(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    prompt: str,
    expected_mode: FlowStepReviewMode | None,
) -> None:
    state = _resolved_state()
    state.checkpoint_intents = [
        CheckpointIntent(
            producer_kind="report_text",
            operation="set",
            mode=FlowStepReviewMode.VIEW,
            confidence="high",
            evidence=["quote:user_message:prior:Approve the report."],
        )
    ]
    monkeypatch.setattr(
        runtime,
        "build_planning_state_from_conversation",
        MagicMock(return_value=state),
    )
    update: dict[str, object] = {
        "operation": operation,
        "producer_kind": "report_text",
        "confidence": "high",
        "reason": "The current user changed report review requirements.",
        "evidence": [_cited(prompt)],
    }
    if expected_mode is not None:
        update["mode"] = expected_mode.value
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps({"checkpoint_updates": [update]})
    )

    context = await build_runtime_discovery_context(
        [
            ConversationMessage(
                message_id="user-1",
                role="user",
                content=prompt,
            )
        ],
        litellm_client=litellm_client,
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=100_000,
        max_output_tokens=2_000,
    )

    litellm_client.acompletion.assert_awaited_once()
    if expected_mode is None:
        assert [
            (intent.producer_kind, intent.operation, intent.mode)
            for intent in context.planning_state.checkpoint_intents
        ] == [("report_text", "clear", None)]
    else:
        assert [
            (intent.producer_kind, intent.operation, intent.mode)
            for intent in context.planning_state.checkpoint_intents
        ] == [("report_text", "set", expected_mode)]


@pytest.mark.asyncio
async def test_runtime_does_not_mutate_planning_state_when_metadata_admission_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = PlanningState(
        fcm_version=FCM_VERSION,
        planner_contract_version=PLANNER_CONTRACT_VERSION,
        builder_schema_version=BUILDER_SCHEMA_VERSION,
    )
    monkeypatch.setattr(
        runtime,
        "build_planning_state_from_conversation",
        MagicMock(return_value=state),
    )
    monkeypatch.setattr(
        runtime,
        "slot_classification_metadata_from_attempt",
        MagicMock(side_effect=ValueError("metadata admission failed")),
    )
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "primary_runtime_input",
                        "value": "text",
                        "confidence": "high",
                        "reason": "The user supplied plain text.",
                        "evidence": [_cited("plain text")],
                        "evidence_level": "explicit",
                    }
                ]
            }
        )
    )

    with pytest.raises(ValueError, match="metadata admission failed"):
        await build_runtime_discovery_context(
            [
                ConversationMessage(
                    message_id="user-1",
                    role="user",
                    content="plain text",
                )
            ],
            litellm_client=litellm_client,
            completion_model_route=_route(),
            tenant_id=uuid4(),
            max_input_tokens=100_000,
            max_output_tokens=2_000,
        )

    assert state.resolved_slots == {}


@pytest.mark.asyncio
async def test_runtime_classifies_named_json_fields_after_slots_are_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _resolved_state()
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_json",
    )
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [],
                "file_roles": [],
                "checkpoint_updates": [],
                "form_intake": None,
                "output_schema_fields": {
                    "operation": "update",
                    "field_names": ["sökta insatser", "status"],
                    "removed_field_names": [],
                    "confidence": "high",
                    "reason": "The user explicitly named the JSON fields.",
                    "evidence": [
                        {
                            "source_id": "user_message:user-1",
                            "quote": "sökta insatser och status",
                        }
                    ],
                },
                "example_output_constraints": None,
                "schema_direction": None,
                "secondary_obligations": [],
                "assumptions": [],
                "contradictions": [],
            }
        )
    )
    monkeypatch.setattr(
        runtime,
        "build_planning_state_from_conversation",
        MagicMock(return_value=state),
    )

    context = await build_runtime_discovery_context(
        [
            ConversationMessage(
                message_id="user-1",
                role="user",
                content="JSON-resultatet ska innehålla sökta insatser och status.",
            )
        ],
        litellm_client=litellm_client,
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=100_000,
        max_output_tokens=2_000,
    )

    litellm_client.acompletion.assert_awaited_once()
    evidence = context.planning_state.output_schema_evidence
    assert evidence is not None
    assert evidence.source == "prose_field_names"
    assert evidence.json_schema["properties"] == {
        "sokta_insatser": {},
        "status": {},
    }

    assert context.slot_classification_metadata is not None
    persisted_metadata = metadata_with_slot_classification(
        {
            "question_answer": {
                "question_id": "terminal_output",
                "selected_option_id": "structured_json",
                "selected_value": "structured_json",
            }
        },
        context.slot_classification_metadata,
    )
    assert persisted_metadata is not None
    replayed = build_planning_state_from_conversation(
        [
            ConversationMessage(
                message_id="user-1",
                role="user",
                content="JSON-resultatet ska innehålla sökta insatser och status.",
                metadata=persisted_metadata,
            )
        ]
    )
    assert replayed.output_schema_evidence is not None
    assert replayed.output_schema_evidence.json_schema["properties"] == {
        "sokta_insatser": {},
        "status": {},
    }

    replayed.resolved_slots = context.planning_state.resolved_slots.copy()
    draft = derive_architecture_commit_draft(replayed)
    assert draft is not None
    replayed.architecture_commit = finalize_architecture_commit(draft)
    confirmation = resolve_turn_control(
        session_state=replayed,
        selected_discovery_question_ids=(),
        confirmed_attachment_evidence_fingerprint=None,
        ui_language="sv",
    ).decision
    assert isinstance(confirmation, ConfirmRequirements)
    assert "sokta_insatser" in confirmation.payload.summary

    proposal_prompt = build_plan_proposal_system_prompt(
        planning_state=replayed,
        confirmed_requirements=confirmation.payload,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[],
            available_kbs=[],
        ),
    )
    assert "sokta_insatser" in proposal_prompt


@pytest.mark.asyncio
async def test_runtime_atomically_resolves_json_terminal_and_named_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _resolved_state()
    state.resolved_slots.pop("terminal_output", None)
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "terminal_output",
                        "value": "structured_json",
                        "confidence": "high",
                        "reason": "The user requests a machine-readable result.",
                        "evidence": [
                            {
                                "source_id": "user_message:user-1",
                                "quote": "JSON with case_id and status",
                            }
                        ],
                        "evidence_level": "explicit",
                    }
                ],
                "file_roles": [],
                "checkpoint_updates": [],
                "form_intake": None,
                "output_schema_fields": {
                    "operation": "update",
                    "field_names": ["case_id", "status"],
                    "removed_field_names": [],
                    "confidence": "high",
                    "reason": "The user explicitly named the JSON fields.",
                    "evidence": [
                        {
                            "source_id": "user_message:user-1",
                            "quote": "JSON with case_id and status",
                        }
                    ],
                },
                "example_output_constraints": None,
                "schema_direction": None,
                "secondary_obligations": [],
                "assumptions": [],
                "contradictions": [],
            }
        )
    )
    monkeypatch.setattr(
        runtime,
        "build_planning_state_from_conversation",
        MagicMock(return_value=state),
    )

    context = await build_runtime_discovery_context(
        [
            ConversationMessage(
                message_id="user-1",
                role="user",
                content="Return JSON with case_id and status.",
            )
        ],
        litellm_client=litellm_client,
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=100_000,
        max_output_tokens=2_000,
    )

    assert context.planning_state.resolved_slots["terminal_output"].value == (
        "structured_json"
    )
    evidence = context.planning_state.output_schema_evidence
    assert evidence is not None
    assert evidence.json_schema["properties"] == {"case_id": {}, "status": {}}
    assert context.slot_classification_metadata is not None
    assert context.slot_classification_metadata.output_schema_fields is not None


@pytest.mark.asyncio
async def test_runtime_updates_replayed_field_snapshot_from_current_delta() -> None:
    prior_source = SlotClassificationSource(
        source_id="user_message:user-1",
        kind="user_message",
        text="Return JSON with case_id and status.",
        message_id="user-1",
    )
    result = SlotClassificationResult(
        slots=(
            ClassifiedSlot(
                slot_name="terminal_output",
                value="structured_json",
                confidence="high",
                reason="The user requested JSON.",
                evidence=(
                    ClassifiedEvidence(
                        source_id=prior_source.source_id,
                        quote=prior_source.text,
                    ),
                ),
                evidence_level="explicit",
            ),
        ),
    )
    prior_snapshot = (
        SlotClassificationOutputSchemaFieldsMetadata.from_materialized_state(
            operation="replace",
            field_names=("case_id", "status"),
            confidence="high",
            reason="Initial materialized field snapshot.",
            evidence=(
                ClassifiedEvidence(
                    source_id=prior_source.source_id,
                    quote=prior_source.text,
                ),
            ),
        )
    )
    prior_classification = slot_classification_metadata_from_attempt(
        SlotClassificationAttempt(outcome="resolved", result=result),
        prompt_hash="a" * 64,
        classification_input=SlotClassificationInput(sources=(prior_source,)),
        model="openai/gpt-test",
        provider="openai",
        output_schema_fields_snapshot=prior_snapshot,
    )
    assert prior_classification is not None
    prior_metadata = metadata_with_slot_classification(None, prior_classification)
    assert prior_metadata is not None
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [],
                "file_roles": [],
                "checkpoint_updates": [],
                "form_intake": None,
                "output_schema_fields": {
                    "operation": "update",
                    "field_names": ["priority"],
                    "removed_field_names": [],
                    "confidence": "high",
                    "reason": "The user added one field.",
                    "evidence": [
                        {
                            "source_id": "user_message:user-2",
                            "quote": "Also add priority",
                        }
                    ],
                },
                "example_output_constraints": None,
                "schema_direction": None,
                "secondary_obligations": [],
                "assumptions": [],
                "contradictions": [],
            }
        )
    )
    context = await build_runtime_discovery_context(
        [
            ConversationMessage(
                message_id="user-1",
                role="user",
                content=prior_source.text,
                metadata=prior_metadata,
            ),
            ConversationMessage(
                message_id="user-2",
                role="user",
                content="Also add priority.",
            ),
        ],
        litellm_client=litellm_client,
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=100_000,
        max_output_tokens=2_000,
        ui_language="en",
    )

    evidence = context.planning_state.output_schema_evidence
    assert evidence is not None
    assert evidence.json_schema["properties"] == {
        "case_id": {},
        "status": {},
        "priority": {},
    }
    call = litellm_client.acompletion.await_args
    assert call is not None
    system_prompt = call.kwargs["messages"][0]["content"]
    user_prompt = call.kwargs["messages"][1]["content"]
    assert "Report only additions or removals explicitly requested" in system_prompt
    assert '["case_id", "status"]' not in user_prompt
    assert context.slot_classification_metadata is not None
    materialized = context.slot_classification_metadata.output_schema_fields
    assert materialized is not None
    assert materialized.field_names == ["case_id", "status", "priority"]
    assert {item.source_id for item in materialized.evidence} == {
        "user_message:user-1",
        "user_message:user-2",
    }


def test_runtime_does_not_materialize_low_confidence_output_field_snapshot() -> None:
    state = _resolved_state()
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_json",
    )
    classified = ClassifiedOutputSchemaFieldDelta(
        operation="update",
        field_names=("case_id",),
        confidence="low",
        reason="The field name was uncertain.",
        evidence=(
            ClassifiedEvidence(
                source_id="user_message:user-1",
                quote="Maybe case_id.",
            ),
        ),
    )

    assert (
        runtime._materialized_output_schema_field_snapshot(
            state,
            classified_fields=classified,
            prior_classification=None,
        )
        is None
    )


@pytest.mark.asyncio
async def test_runtime_discards_named_json_fields_for_non_json_terminal_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _resolved_state()
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
    )
    state.resolved_slots["runtime_metadata_fields"] = ResolvedSlot(
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
                "slots": [],
                "file_roles": [],
                "checkpoint_updates": [],
                "form_intake": None,
                "output_schema_fields": {
                    "operation": "update",
                    "field_names": ["case_id", "status"],
                    "removed_field_names": [],
                    "confidence": "high",
                    "reason": "The user named fields for an intermediate JSON matrix.",
                    "evidence": [
                        {
                            "source_id": "user_message:user-1",
                            "quote": "case_id och status",
                        }
                    ],
                },
                "example_output_constraints": None,
                "schema_direction": None,
                "secondary_obligations": [],
                "assumptions": [],
                "contradictions": [],
            }
        )
    )
    monkeypatch.setattr(
        runtime,
        "build_planning_state_from_conversation",
        MagicMock(return_value=state),
    )

    context = await build_runtime_discovery_context(
        [
            ConversationMessage(
                message_id="user-1",
                role="user",
                content="PDF-rapporten bygger på en JSON-matris med case_id och status.",
            )
        ],
        litellm_client=litellm_client,
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=100_000,
        max_output_tokens=2_000,
    )

    assert context.planning_state.output_schema_evidence is None
    assert context.slot_classification_result is not None
    assert context.slot_classification_result.output_schema_fields is None
    assert context.slot_classification_metadata is not None
    assert context.slot_classification_metadata.output_schema_fields is None


@pytest.mark.asyncio
async def test_runtime_planning_state_overlays_heuristic_slots_with_model_evidence() -> (
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
                        "reason": "mentions text input",
                        "evidence": [_cited("klistra in ett kundmeddelande")],
                    },
                    {
                        "slot_name": "terminal_output",
                        "value": "structured_text",
                        "confidence": "medium",
                        "reason": "asks for a summary",
                        "evidence": [_cited("få en tydlig sammanfattning")],
                    },
                ]
            }
        )
    )

    state = (
        await build_runtime_discovery_context(
            [
                ConversationMessage(
                    message_id="user-1",
                    role="user",
                    content=(
                        "Jag vill klistra in ett kundmeddelande och få en tydlig "
                        "sammanfattning."
                    ),
                )
            ],
            litellm_client=litellm_client,
            completion_model_route=_route(),
            tenant_id=uuid4(),
            max_input_tokens=100_000,
            max_output_tokens=2_000,
            ui_language="sv",
        )
    ).planning_state

    assert state.resolved_slots["primary_runtime_input"].source == "model"
    assert state.resolved_slots["primary_runtime_input"].value == "text"
    assert state.resolved_slots["terminal_output"].source == "model"
    assert state.resolved_slots["terminal_output"].value == "structured_text"

    messages = litellm_client.acompletion.await_args.kwargs["messages"]
    prompt = "\n".join(message["content"] for message in messages)
    assert "\n- primary_runtime_input:" in prompt
    assert "terminal_output" in prompt


@pytest.mark.asyncio
async def test_runtime_planning_state_lets_classifier_correct_heuristic_input_guess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    heuristic_state = PlanningState.empty()
    heuristic_state.resolved_slots = {
        "primary_runtime_input": _slot(
            "primary_runtime_input",
            "audio",
            source="heuristic",
            confidence="high",
        )
    }
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "primary_runtime_input",
                        "value": "documents",
                        "confidence": "high",
                        "reason": "the user uploads written material",
                        "evidence": [_cited("ladda upp flera PDF-dokument")],
                    },
                ]
            }
        )
    )
    monkeypatch.setattr(
        runtime,
        "build_planning_state_from_conversation",
        lambda *_args, **_kwargs: heuristic_state,
    )

    state = (
        await build_runtime_discovery_context(
            [
                ConversationMessage(
                    message_id="user-1",
                    role="user",
                    content="Jag vill ladda upp flera PDF-dokument och analysera dem.",
                )
            ],
            litellm_client=litellm_client,
            completion_model_route=_route(),
            tenant_id=uuid4(),
            max_input_tokens=100_000,
            max_output_tokens=2_000,
            ui_language="sv",
        )
    ).planning_state

    slot = state.resolved_slots["primary_runtime_input"]
    assert slot.source == "model"
    assert slot.value == "documents"
    assert "quote:user_message:user-1:ladda upp flera PDF-dokument" in slot.evidence


@pytest.mark.asyncio
async def test_runtime_planning_state_passes_uploaded_file_evidence_to_classifier() -> (
    None
):
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps({"slots": [], "assumptions": [], "contradictions": []})
    )

    await build_runtime_discovery_context(
        [
            ConversationMessage(
                role="user",
                content="Jag vill bygga ett transkriberingsflöde.",
                metadata={"ui_language": "sv"},
            )
        ],
        litellm_client=litellm_client,
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=100_000,
        max_output_tokens=2_000,
        ui_language="sv",
        attachment_context=_attachment_context(),
    )

    messages = litellm_client.acompletion.await_args.kwargs["messages"]
    prompt = "\n".join(message["content"] for message in messages)
    assert '"kind": "uploaded_file"' in prompt
    assert "filename: beslutsmall.docx" in prompt
    assert "has_readable_text: false" in prompt


@pytest.mark.asyncio
async def test_runtime_planning_state_uses_classifier_for_semantic_file_roles() -> None:
    file_id = uuid4()
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [],
                "file_roles": [
                    {
                        "file_id": str(file_id),
                        "role": "example_output",
                        "confidence": "medium",
                        "reason": "conversation ties the upload to desired output",
                        "evidence": [_cited("så här ska rapporten se ut")],
                        "evidence_level": "explicit",
                    }
                ],
            }
        )
    )

    state = (
        await build_runtime_discovery_context(
            [
                ConversationMessage(
                    message_id="user-1",
                    role="user",
                    content=(
                        "Jag bifogar en rapport som visar ungefär så här ska "
                        "rapporten se ut."
                    ),
                    metadata={"ui_language": "sv"},
                )
            ],
            litellm_client=litellm_client,
            completion_model_route=_route(),
            tenant_id=uuid4(),
            max_input_tokens=100_000,
            max_output_tokens=2_000,
            ui_language="sv",
            attachment_context=AIBuilderAttachmentContext(
                context=None,
                evidence=(
                    AIBuilderAttachmentEvidence(
                        file_id=file_id,
                        filename="exempelrapport.pdf",
                        file_type=FileType.DOCUMENT,
                        mimetype="application/pdf",
                        has_readable_text=True,
                        excerpt="Titel\nSammanfattning\nRekommendation",
                        coverage="fully_seen",
                        inferred_role="context_only",
                        role_confidence="low",
                        role_evidence=("fallback:unclassified_file",),
                    ),
                ),
                included_file_ids=[],
                total_chars=0,
                truncated=False,
            ),
        )
    ).planning_state

    role = state.file_roles[0]
    assert role.role == "example_output"
    assert role.source == "model"
    assert role.confidence == "medium"
    assert "quote:user_message:user-1:så här ska rapporten se ut" in role.evidence


@pytest.mark.asyncio
async def test_runtime_planning_state_classifies_example_output_shape_in_one_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_id = uuid4()
    initial_state = PlanningState.empty()
    initial_state.resolved_slots = {
        "primary_runtime_input": _slot(
            "primary_runtime_input",
            "documents",
            source="structured_answer",
        ),
        "document_material_scope": _slot(
            "document_material_scope",
            "multiple_documents_case",
            source="structured_answer",
        ),
    }
    initial_state.file_roles = [
        FileRoleEvidence(
            file_id=file_id,
            filename="exempelrapport.pdf",
            file_type="document",
            mimetype="application/pdf",
            has_readable_text=True,
            coverage="fully_seen",
            role="context_only",
            source="heuristic",
            confidence="low",
            evidence=["fallback:unclassified_file"],
            candidate_roles=["context_only"],
        )
    ]
    monkeypatch.setattr(
        runtime,
        "build_planning_state_from_conversation",
        lambda *_args, **_kwargs: initial_state,
    )
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "terminal_output",
                        "value": "pdf_document",
                        "confidence": "high",
                        "reason": "user requests a PDF report",
                        "evidence": [_cited("PDF-rapport med samma upplägg")],
                        "evidence_level": "explicit",
                    },
                    {
                        "slot_name": "report_disposition",
                        "value": "both",
                        "confidence": "high",
                        "reason": "example report shows sections and overview",
                        "evidence": [
                            _cited("samma upplägg som bifogad exempelrapport")
                        ],
                        "evidence_level": "explicit",
                    },
                ],
                "file_roles": [
                    {
                        "file_id": str(file_id),
                        "role": "example_output",
                        "confidence": "high",
                        "reason": "conversation ties the upload to desired output",
                        "evidence": [_cited("bifogad exempelrapport")],
                        "evidence_level": "explicit",
                    }
                ],
            }
        )
    )
    conversation = [
        ConversationMessage(
            message_id="user-1",
            role="user",
            content=(
                "Jag vill analysera flera dokument och skapa en PDF-rapport med "
                "samma upplägg som bifogad exempelrapport."
            ),
            metadata={"ui_language": "sv"},
        )
    ]

    context = await build_runtime_discovery_context(
        conversation,
        litellm_client=litellm_client,
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=100_000,
        max_output_tokens=2_000,
        ui_language="sv",
        attachment_context=AIBuilderAttachmentContext(
            context=None,
            evidence=(
                AIBuilderAttachmentEvidence(
                    file_id=file_id,
                    filename="exempelrapport.pdf",
                    file_type=FileType.DOCUMENT,
                    mimetype="application/pdf",
                    has_readable_text=True,
                    excerpt="Inledning\nAvsnitt per källa\nSamlad bedömning",
                    coverage="fully_seen",
                    inferred_role="context_only",
                    role_confidence="low",
                    role_evidence=("fallback:unclassified_file",),
                ),
            ),
            included_file_ids=[],
            total_chars=0,
            truncated=False,
        ),
    )

    assert context.planning_state.resolved_slots["terminal_output"].value == (
        "pdf_document"
    )
    assert context.planning_state.resolved_slots["report_disposition"].value == "both"
    assert context.planning_state.file_roles[0].role == "example_output"
    allowed_schema = litellm_client.acompletion.await_args.kwargs["response_format"][
        "json_schema"
    ]["schema"]
    offered_slots = {
        variant["properties"]["slot_name"]["enum"][0]
        for variant in allowed_schema["properties"]["slots"]["items"]["anyOf"]
    }
    assert "report_disposition" in offered_slots

    analysis = analyze_discovery(
        conversation,
        planning_state=context.planning_state,
        slot_classification_result=context.slot_classification_result,
    )
    assert "report_disposition" not in analysis.selected_question_ids


@pytest.mark.asyncio
async def test_uploaded_docx_evidence_alone_does_not_deterministically_resolve_terminal_output() -> (
    None
):
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps({"slots": [], "assumptions": [], "contradictions": []})
    )

    state = (
        await build_runtime_discovery_context(
            [
                ConversationMessage(
                    role="user",
                    content="Jag vill bygga ett transkriberingsflöde.",
                    metadata={"ui_language": "sv"},
                )
            ],
            litellm_client=litellm_client,
            completion_model_route=_route(),
            tenant_id=uuid4(),
            max_input_tokens=100_000,
            max_output_tokens=2_000,
            ui_language="sv",
            attachment_context=_attachment_context(),
        )
    ).planning_state

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
                        "evidence": [_cited("tar emot JSON")],
                    },
                    {
                        "slot_name": "terminal_output",
                        "value": "structured_json",
                        "confidence": "high",
                        "reason": "the user asks for JSON output",
                        "evidence": [_cited("returnerar JSON")],
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

    state = (
        await build_runtime_discovery_context(
            [
                ConversationMessage(
                    message_id="user-1",
                    role="user",
                    content=(
                        "Jag vill bygga ett flöde som tar emot JSON och returnerar JSON."
                    ),
                )
            ],
            litellm_client=litellm_client,
            completion_model_route=_route(),
            tenant_id=uuid4(),
            max_input_tokens=100_000,
            max_output_tokens=2_000,
            ui_language="sv",
        )
    ).planning_state

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
                        "evidence": [_cited("Jag vet inte exakt vilket format")],
                        "evidence_level": "explicit",
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

    state = (
        await build_runtime_discovery_context(
            [
                ConversationMessage(
                    message_id="user-1",
                    role="user",
                    content=(
                        "Jag har en svensk ljudinspelning från ett möte. Jag vet "
                        "inte exakt vilket format slutresultatet ska vara ännu."
                    ),
                    metadata={"ui_language": "sv"},
                )
            ],
            litellm_client=litellm_client,
            completion_model_route=_route(),
            tenant_id=uuid4(),
            max_input_tokens=100_000,
            max_output_tokens=2_000,
            ui_language="sv",
        )
    ).planning_state

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
                        "evidence": [_cited("sammanfattar innehållet tydligt")],
                    },
                    {
                        "slot_name": "terminal_output",
                        "value": "structured_text",
                        "confidence": "high",
                        "reason": "summary requested",
                        "evidence": [_cited("sammanfattar innehållet tydligt")],
                        "evidence_level": "explicit",
                    },
                ]
            }
        )
    )

    state = (
        await build_runtime_discovery_context(
            [
                ConversationMessage(
                    message_id="user-structured",
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
                    message_id="user-1",
                    role="user",
                    content="Bygg ett flöde som sammanfattar innehållet tydligt.",
                ),
            ],
            litellm_client=litellm_client,
            completion_model_route=_route(),
            tenant_id=uuid4(),
            max_input_tokens=100_000,
            max_output_tokens=2_000,
            ui_language="sv",
        )
    ).planning_state

    assert state.resolved_slots["primary_runtime_input"].source == "structured_answer"
    assert state.resolved_slots["primary_runtime_input"].value == "text"
    assert state.resolved_slots["terminal_output"].source == "model"
    assert state.resolved_slots["terminal_output"].value == "structured_text"

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
                        "slot_name": "post_processing_goal",
                        "value": "extract_key_information",
                        "confidence": "high",
                        "reason": "the flow extracts support-routing information",
                        "evidence": [_cited("klassificerar avsikt och prioritet")],
                        "evidence_level": "explicit",
                    },
                    {
                        "slot_name": "primary_runtime_input",
                        "value": "text",
                        "confidence": "high",
                        "reason": "the source material is user-provided prose",
                        "evidence": [_cited("klistrar in ett kundmeddelande")],
                        "evidence_level": "explicit",
                    },
                    {
                        "slot_name": "terminal_output",
                        "value": "structured_json",
                        "confidence": "high",
                        "reason": "structured data is requested for downstream use",
                        "evidence": [_cited("strukturerad data")],
                        "evidence_level": "explicit",
                    },
                ]
            }
        )
    )

    provider_kwargs: dict[str, object] = {
        "custom_llm_provider": "azure",
        "api_base": "https://flow-builder.example.com",
        "api_version": "2026-01-01",
        "deployment_name": "flow-builder",
        "api_key": "test-only-secret",
    }
    result = await build_discovery_runtime_result(
        [
            ConversationMessage(
                message_id="user-1",
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
        completion_model_route=_route(
            model="azure/gpt-test",
            provider_type="azure",
            kwargs=provider_kwargs,
        ),
        tenant_id=uuid4(),
        max_input_tokens=100_000,
        max_output_tokens=2_000,
        ui_language="sv",
    )
    analysis = result.discovery_analysis

    question_ids = {
        issue.suggestion.question_id
        for issue in analysis.blocking_issues
        if issue.suggestion is not None
    }
    assert "input_material_mode" not in question_ids
    assert "final_output_mode" not in question_ids
    assert question_ids == {"runtime_metadata_fields"}
    assert analysis.ready_for_confirmation is False
    assert result.slot_classification_metadata is not None
    assert result.slot_classification_metadata.provider == (
        slot_classification_provider_identity(
            provider_type="azure",
            litellm_kwargs=provider_kwargs,
        )
    )
    assert {
        slot.slot_name: (slot.value, slot.evidence_level)
        for slot in result.slot_classification_metadata.slots
    } == {
        "post_processing_goal": ("extract_key_information", "explicit"),
        "primary_runtime_input": ("text", "explicit"),
        "terminal_output": ("structured_json", "explicit"),
    }

    messages = litellm_client.acompletion.await_args.kwargs["messages"]
    prompt = "\n".join(message["content"] for message in messages)
    assert "primary_runtime_input" in prompt
    assert "terminal_output" in prompt


@pytest.mark.asyncio
async def test_runtime_discovery_blocks_output_classification_when_user_is_uncertain() -> (
    None
):
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(json.dumps({"slots": []}))

    result = await build_discovery_runtime_result(
        [
            ConversationMessage(
                message_id="user-1",
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
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=100_000,
        max_output_tokens=2_000,
        ui_language="sv",
    )
    analysis = result.discovery_analysis

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
                        "evidence": [_cited("flera leverantörsavtal och bilagor")],
                        "evidence_level": "explicit",
                    },
                    {
                        "slot_name": "document_material_scope",
                        "value": "multiple_documents_case",
                        "confidence": "high",
                        "reason": "the user says several related files",
                        "evidence": [_cited("flera leverantörsavtal och bilagor")],
                        "evidence_level": "explicit",
                    },
                    {
                        "slot_name": "terminal_output",
                        "value": "structured_json",
                        "confidence": "high",
                        "reason": "structured JSON is requested for another system",
                        "evidence": [_cited("strukturerad JSON")],
                        "evidence_level": "explicit",
                    },
                    {
                        "slot_name": "post_processing_goal",
                        "value": "risk_or_issue_review",
                        "confidence": "high",
                        "reason": "the user asks to extract risks",
                        "evidence": [
                            _cited(
                                "extraherar risker, rekommendationer och öppna frågor"
                            )
                        ],
                        "evidence_level": "explicit",
                    },
                ]
            }
        )
    )

    result = await build_discovery_runtime_result(
        [
            ConversationMessage(
                message_id="user-1",
                role="user",
                content=(
                    "Skapa ett flöde som tar emot flera leverantörsavtal och "
                    "bilagor, extraherar risker, rekommendationer och öppna "
                    "frågor, låter en människa granska, och returnerar "
                    "strukturerad JSON för ett uppföljningssystem."
                ),
                metadata={"ui_language": "sv"},
            )
        ],
        litellm_client=litellm_client,
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=100_000,
        max_output_tokens=2_000,
        ui_language="sv",
    )
    analysis = result.discovery_analysis

    question_ids = {
        issue.suggestion.question_id
        for issue in analysis.blocking_issues
        if issue.suggestion is not None
    }
    assert "input_material_mode" not in question_ids
    assert "document_material_scope" not in question_ids
    assert "final_output_mode" not in question_ids
    assert question_ids == {"runtime_metadata_fields"}
    assert analysis.ready_for_confirmation is False
    assert result.slot_classification_metadata is not None
    assert {
        slot.slot_name: slot.value for slot in result.slot_classification_metadata.slots
    } == {
        "primary_runtime_input": "documents",
        "document_material_scope": "multiple_documents_case",
        "terminal_output": "structured_json",
        "post_processing_goal": "risk_or_issue_review",
    }


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
                        "evidence": [_cited("klistrar in intervjusvar")],
                    },
                    {
                        "slot_name": "terminal_output",
                        "value": "structured_text",
                        "confidence": "high",
                        "reason": "a readable summary is requested",
                        "evidence": [_cited("läsbar sammanfattning")],
                    },
                    {
                        "slot_name": "post_processing_goal",
                        "value": "summarize_or_overview",
                        "confidence": "high",
                        "reason": "the user requests a readable summary",
                        "evidence": [_cited("läsbar sammanfattning")],
                    },
                ]
            }
        )
    )

    conversation = [
        ConversationMessage(
            message_id="user-1",
            role="user",
            content=(
                "Bygg ett flöde där användaren klistrar in intervjusvar och får "
                "en läsbar sammanfattning med viktiga teman."
            ),
            metadata={"ui_language": "sv"},
        )
    ]
    result = await build_discovery_runtime_result(
        conversation,
        litellm_client=litellm_client,
        completion_model_route=_route(),
        tenant_id=uuid4(),
        max_input_tokens=100_000,
        max_output_tokens=2_000,
        ui_language="sv",
    )
    message = build_discovery_block_message(
        conversation,
        analysis=result.discovery_analysis,
    )

    assert message == (
        "Det är fortfarande oklart om användaren ska ange extra metadata vid körning."
    )
    assert result.discovery_analysis.next_issue is not None
    assert result.discovery_analysis.next_issue.suggestion is not None
    assert (
        result.discovery_analysis.next_issue.suggestion.question_id
        == "runtime_metadata_fields"
    )
    assert result.discovery_analysis.ready_for_confirmation is False
    assert result.planning_state.resolved_slots["primary_runtime_input"].source == (
        "model"
    )
    assert result.planning_state.resolved_slots["terminal_output"].source == "model"
    assert result.planning_state.resolved_slots["post_processing_goal"].source == (
        "model"
    )
    litellm_client.acompletion.assert_awaited_once()


def test_targeted_bias_canonicalizes_legacy_question_id_to_slot() -> None:
    conversation = [
        ConversationMessage(
            role="assistant",
            content="Vilket format?",
            metadata={"question_id": "final_output_mode"},
        ),
        ConversationMessage(
            message_id="user-answer-1",
            role="user",
            content="en fil jag kan ladda ner",
        ),
    ]
    bias = _targeted_classification_bias(
        conversation,
        {"terminal_output": {"docx_document", "structured_text"}},
        _classification_input(conversation),
    )

    assert bias is not None
    assert bias.target_slot_name == "terminal_output"
    assert bias.asked_question_id == "terminal_output"
    assert bias.answer_source_id == "user_message:user-answer-1"


def test_targeted_bias_uses_neutral_response_identity_after_compaction() -> None:
    conversation = [
        ConversationMessage(
            message_id="user-answer-1",
            role="user",
            content="en fil jag kan ladda ner",
            metadata={
                "question_response": {"question_id": "final_output_mode"},
            },
        ),
    ]
    classification_input = _classification_input(conversation)

    bias = _targeted_classification_bias(
        conversation,
        {"terminal_output": {"docx_document", "structured_text"}},
        classification_input,
    )

    assert classification_input.sources[0].question_id == "terminal_output"
    assert bias is not None
    assert bias.target_slot_name == "terminal_output"
    assert bias.answer_source_id == "user_message:user-answer-1"


def test_targeted_bias_is_none_when_target_already_resolved() -> None:
    conversation = [
        ConversationMessage(
            role="assistant",
            content="Vilket format?",
            metadata={"question_id": "final_output_mode"},
        ),
        ConversationMessage(role="user", content="en fil"),
    ]
    bias = _targeted_classification_bias(
        conversation,
        {"primary_runtime_input": {"text", "documents"}},
        _classification_input(conversation),
    )

    assert bias is None
