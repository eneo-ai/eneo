from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.completion_service import (
    ResolvedCompletionModelRoute,
)
from eneo.files.file_models import FileType
from eneo.flows.ai_builder import ai_builder_discovery_runtime as runtime
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AI_BUILDER_MAX_ATTACHMENTS,
    AIBuilderAttachmentContext,
    AIBuilderAttachmentEvidence,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    metadata_with_slot_classification,
    slot_classification_metadata_from_result,
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
from eneo.flows.ai_builder.ai_builder_output_schema_evidence import (
    build_output_schema_evidence,
)
from eneo.flows.ai_builder.ai_builder_slot_classifier import (
    UNKNOWN_SLOT_VALUE,
    ClassifiedEvidence,
    ClassifiedFileRole,
    SlotClassificationInput,
    SlotClassificationResult,
    SlotClassificationSource,
    slot_classification_provider_identity,
)
from eneo.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    ExampleOutputCitation,
    ExampleOutputConstraintEvidence,
    ExampleOutputSourceCoverage,
    FileRoleEvidence,
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


def _route(
    *,
    model: str = "gpt-test",
    kwargs: dict[str, object] | None = None,
) -> ResolvedCompletionModelRoute:
    return ResolvedCompletionModelRoute(
        litellm_model=model,
        litellm_kwargs=kwargs or {},
        supported_model_kwargs=SupportedModelKwargs(
            temperature=ModelKwargCapability(supported=True)
        ),
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

    classification_input = build_slot_classification_input(
        conversation,
        attachment_context,
    )

    assert classification_input.sources[0].source_id == "user_message:user-1"
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
        build_slot_classification_input([], attachment_context)

    assert error.value.code is AIBuilderErrorCode.BAD_REQUEST
    assert str(AI_BUILDER_MAX_ATTACHMENTS) in str(error.value)


def test_slot_classification_input_preserves_selected_option_only_answer() -> None:
    classification_input = build_slot_classification_input(
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
    classification_input = build_slot_classification_input(
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


def test_slot_classification_input_bounds_transcript_without_starving_late_sources() -> (
    None
):
    classification_input = build_slot_classification_input(
        [
            ConversationMessage(
                message_id="user-old",
                role="user",
                content="old:" + "A" * 9_000,
            ),
            ConversationMessage(
                message_id="user-answer",
                role="user",
                content="structured_json",
                metadata={
                    "question_answer": {
                        "question_id": "terminal_output",
                        "selected_value": "structured_json",
                    }
                },
            ),
            ConversationMessage(
                message_id="user-latest",
                role="user",
                content="latest:" + "B" * 9_000,
            ),
        ],
        None,
    )

    assert [source.source_id for source in classification_input.sources] == [
        "user_message:user-old",
        "structured_answer:user-answer:0",
        "user_message:user-latest",
    ]
    assert sum(len(source.text) for source in classification_input.sources) == (
        runtime._MAX_CLASSIFICATION_TRANSCRIPT_CHARS
    )
    assert classification_input.sources[0].truncated is True
    assert classification_input.sources[1].truncated is False
    assert classification_input.sources[2].truncated is True
    assert classification_input.sources[1].selected_value == "structured_json"
    assert classification_input.sources[-1].text.startswith("latest:")


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
async def test_runtime_planning_state_skips_model_when_resolvable_slots_are_strong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    litellm_client = AsyncMock()
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
        )
    ).planning_state

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
        )
    ).planning_state

    assert state.resolved_slots["runtime_metadata_fields"].source == "model"
    assert (
        state.resolved_slots["runtime_metadata_fields"].value == "basic_case_metadata"
    )


@pytest.mark.asyncio
async def test_runtime_planning_state_skips_model_when_freeform_text_is_empty() -> None:
    litellm_client = AsyncMock()

    await build_runtime_discovery_context(
        [ConversationMessage(role="user", content="   ")],
        litellm_client=litellm_client,
        completion_model_route=_route(),
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
    classification = slot_classification_metadata_from_result(
        SlotClassificationResult(
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
        ),
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
                output_schema_evidence=build_output_schema_evidence(
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
    assert slot.source == "heuristic"
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
async def test_runtime_applies_attachment_json_schema_evidence_without_model_call() -> (
    None
):
    file_id = uuid4()
    attachment_evidence = build_output_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {"decision": {"type": "string"}},
        },
        source="attachment_json_schema",
        source_file_ids=(file_id,),
        confidence="high",
        evidence=[f"file:{file_id}:json_schema_attachment"],
    )

    state = (
        await build_runtime_discovery_context(
            [],
            tenant_id=uuid4(),
            allow_classification=False,
            attachment_context=AIBuilderAttachmentContext(
                context=None,
                evidence=(),
                included_file_ids=[],
                total_chars=0,
                truncated=False,
                output_schema_evidence=attachment_evidence,
            ),
        )
    ).planning_state

    assert state.output_schema_evidence is attachment_evidence
    terminal_output = state.resolved_slots["terminal_output"]
    assert terminal_output.value == "structured_json"
    assert terminal_output.source == "heuristic"


@pytest.mark.asyncio
async def test_runtime_does_not_treat_template_placeholders_as_json_terminal() -> None:
    file_id = uuid4()
    template_evidence = build_output_schema_evidence(
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

    assert state.output_schema_evidence is template_evidence
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
        classify = AsyncMock(return_value=classification_result)
        monkeypatch.setattr(runtime, "classify_slots", classify)
        state = (
            await build_runtime_discovery_context(
                [ConversationMessage(role="user", content="Use the attached example.")],
                litellm_client=AsyncMock(),
                completion_model_route=_route(),
                tenant_id=uuid4(),
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
            AsyncMock(return_value=classification_result),
        )
        state = (
            await build_runtime_discovery_context(
                [ConversationMessage(role="user", content="Use the attached example.")],
                litellm_client=AsyncMock(),
                completion_model_route=_route(),
                tenant_id=uuid4(),
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
        allow_classification=False,
    )

    litellm_client.acompletion.assert_not_awaited()


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
        completion_model_route=_route(model="azure/gpt-test", kwargs=provider_kwargs),
        tenant_id=uuid4(),
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
            litellm_model="azure/gpt-test",
            litellm_kwargs=provider_kwargs,
        )
    )
    assert {
        slot.slot_name: (slot.value, slot.evidence_level)
        for slot in result.slot_classification_metadata.slots
    } == {
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
        build_slot_classification_input(conversation, None),
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
    classification_input = build_slot_classification_input(conversation, None)

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
        build_slot_classification_input(conversation, None),
    )

    assert bias is None
