from __future__ import annotations

from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_create_compile_context import (
    CreateCompileContext,
    create_compile_context_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_create_proposal import (
    process_create_intent_arguments as _process_create_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    EMPTY_REQUESTED_OUTPUT_SECTIONS,
    RequestedOutputSections,
)
from eneo.flows.ai_builder.ai_builder_plan_store import build_flow_builder_proposal
from eneo.flows.ai_builder.ai_builder_proposal_intent import FlowInputFieldIntent
from eneo.flows.ai_builder.ai_builder_proposal_policy import (
    build_create_contextual_quality_feedback,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ToolProcessingResult,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableModelResource,
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_fields import (
    DETAILED_RUNTIME_METADATA,
)
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommitDraft,
    CheckpointIntent,
    ConfirmedRuntimeMetadataField,
    MappedFileLimit,
    PlanningState,
    ResolvedSlot,
    StepTriple,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode
from tests.unittests.flows.ai_builder.authoring_command_assertions import (
    assert_create_spec_prepares_through_authoring_command_async,
)


async def process_create_intent_arguments(
    *,
    turn: SessionSendTurn,
    conversation: list[ConversationMessage],
    arguments: dict[str, Any],
    tool_call_id: str,
    available_model_refs: set[str] | None,
    available_kb_refs: set[str] | None,
    resource_catalog: AIBuilderResourceCatalog | None = None,
    planning_state: PlanningState | None = None,
    requested_output_sections: RequestedOutputSections = (
        EMPTY_REQUESTED_OUTPUT_SECTIONS
    ),
) -> ToolProcessingResult:
    return await _process_create_intent_arguments(
        turn=turn,
        conversation=conversation,
        arguments=arguments,
        tool_call_id=tool_call_id,
        available_model_refs=available_model_refs,
        available_kb_refs=available_kb_refs,
        resource_catalog=resource_catalog,
        compile_context=create_compile_context_from_planning_state(
            planning_state,
            requested_output_sections=requested_output_sections,
        ),
    )


def _make_turn(
    *,
    session_id=None,
    tenant_id=None,
    base_planning_state_version: int = 0,
) -> SessionSendTurn:
    return SessionSendTurn(
        session_id=session_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=base_planning_state_version,
    )


def _structured_fan_in_spec() -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Structured report",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extract A",
                assistant_spec=AssistantSpec(instructions="Extract A."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"summary": {"type": "string"}},
                },
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Extract B",
                assistant_spec=AssistantSpec(instructions="Extract B."),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"detail": {"type": "string"}},
                },
            ),
            StepSpec(
                plan_step_ref="step_c",
                name="Write report",
                assistant_spec=AssistantSpec(instructions="Write report."),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            ),
        ],
    )


def _model_resource(local_id: str, name: str) -> AIBuilderAvailableModelResource:
    return {
        "id": local_id,
        "ref": local_id,
        "name": name,
        "display_name": name,
        "provider": "test",
    }


def test_create_contextual_quality_feedback_uses_semantic_remediation() -> None:
    feedback = build_create_contextual_quality_feedback(
        conversation=[],
        spec=_structured_fan_in_spec(),
        aggregation_intent="linear",
        resource_catalog=None,
    ).feedback

    assert feedback is not None
    assert "Quality issues" in feedback
    assert "strukturerade" in feedback.casefold()
    for token in (
        "input_source",
        "uses_previous_fields",
        "input_bindings",
        "{{ step_",
    ):
        assert token not in feedback


@pytest.mark.asyncio
async def test_create_terminal_uses_committed_architecture_despite_negated_file_formats() -> (
    None
):
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="text",
                    output_type="text",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=[],
        )
    )

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[
            ConversationMessage(
                role="user",
                content=("Slutresultatet ska vara text — ingen PDF, ingen DOCX-mall."),
            )
        ],
        arguments={
            "flow_name": "Bygglovsremiss",
            "plan_rationale": "Sammanfatta remissen som text.",
            "steps": [
                {
                    "name": "Sammanfatta remissen",
                    "instructions": "Skriv en tydlig textsammanfattning.",
                }
            ],
        },
        tool_call_id="call-committed-text-terminal",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is not None
    assert result.compiled_proposal.validation.valid
    assert (
        result.compiled_proposal.content.spec.steps[-1].output_type is OutputType.TEXT
    )


@pytest.mark.asyncio
async def test_create_terminal_postcondition_treats_mismatch_as_compiler_defect() -> (
    None
):
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="text",
                    output_type="json",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=[],
        )
    )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_create_proposal."
            "compile_create_intent_to_spec",
            return_value=_structured_fan_in_spec(),
        ),
        pytest.raises(AIBuilderArchitectureError) as exc_info,
    ):
        await process_create_intent_arguments(
            turn=_make_turn(),
            conversation=[
                ConversationMessage(
                    role="user",
                    content="Slutresultatet ska vara strukturerad JSON.",
                )
            ],
            arguments={
                "flow_name": "Strukturerat resultat",
                "plan_rationale": "Returnera ett maskinläsbart resultat.",
                "steps": [
                    {
                        "name": "Strukturera resultat",
                        "instructions": "Returnera resultatet som JSON.",
                    }
                ],
            },
            tool_call_id="call-terminal-postcondition",
            available_model_refs=None,
            available_kb_refs=None,
            planning_state=state,
        )

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.log_context["failure_code"] == (
        "terminal_output_type_mismatch"
    )


@pytest.mark.asyncio
async def test_outline_processing_reports_unknown_resource_from_compiled_spec() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[_model_resource("model-1", "gpt-5.4-nano")],
        available_kbs=[],
    )

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[ConversationMessage(role="user", content="Bygg ett textflöde.")],
        arguments={
            "flow_name": "Unknown model flow",
            "plan_rationale": "Use a missing model ref.",
            "steps": [
                {
                    "name": "Analysera",
                    "instructions": "Analysera texten.",
                    "model_ref": "missing-fast-model",
                }
            ],
        },
        tool_call_id="call-unknown-resource",
        available_model_refs=catalog.model_refs,
        available_kb_refs=None,
        resource_catalog=catalog,
    )

    assert result.compiled_proposal is None
    assert result.failure_kind == "validation"
    assert result.feedback is not None
    assert "Unknown model reference 'missing-fast-model'" in result.feedback
    assert "step 'step_a'.assistant_spec.model_ref" in result.feedback
    assert "model.gpt-5-4-nano" in result.feedback


@pytest.mark.asyncio
async def test_create_compile_disambiguates_duplicate_step_names() -> None:
    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[ConversationMessage(role="user", content="Bygg ett textflöde.")],
        arguments={
            "flow_name": "Duplicate names",
            "plan_rationale": "Two semantic steps accidentally share a name.",
            "steps": [
                {
                    "name": "Förbered PDF-innehåll",
                    "instructions": "Sammanfatta texten.",
                },
                {"name": "Förbered PDF-innehåll", "instructions": "Skriv slutrapport."},
            ],
        },
        tool_call_id="call-duplicate-name",
        available_model_refs=None,
        available_kb_refs=None,
    )

    assert result.compiled_proposal is not None
    assert result.compiled_proposal.validation.valid
    assert [step.name for step in result.compiled_proposal.content.spec.steps] == [
        "Förbered PDF-innehåll",
        "Förbered PDF-innehåll (2)",
    ]


@pytest.mark.asyncio
async def test_outline_validation_failure_preserves_citation_family() -> None:
    invalid_spec = FlowDraftSpecCore(
        flow_name="Invalid cited JSON",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extract JSON",
                assistant_spec=AssistantSpec(instructions="Extract structured data."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"summary": {"type": "string"}},
                },
                output_config={"citation_mode": "inline_inref_sidecar"},
            )
        ],
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_create_proposal."
        "compile_create_intent_to_spec",
        return_value=invalid_spec,
    ):
        result = await _process_create_intent_arguments(
            turn=_make_turn(),
            conversation=[],
            arguments={
                "flow_name": "Invalid cited JSON",
                "plan_rationale": "Exercise final validation telemetry.",
                "steps": [
                    {
                        "name": "Extract JSON",
                        "instructions": "Extract structured data.",
                    }
                ],
            },
            tool_call_id="call-invalid-citation",
            available_model_refs=None,
            available_kb_refs=None,
            compile_context=CreateCompileContext(
                final_output_type=OutputType.JSON,
            ),
        )

    assert result.compiled_proposal is not None
    assert [error.code for error in result.compiled_proposal.validation.errors] == [
        "citation_mode_unsupported"
    ]


@pytest.mark.asyncio
async def test_outline_assembly_rejection_succeeds_after_model_correction() -> None:
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="text",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["document_to_structured_report"],
            required_capabilities=["input_document", "output_mode_pass_through"],
        )
    )

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[
            ConversationMessage(role="user", content="Bygg ett dokumentflöde.")
        ],
        arguments={
            "flow_name": "Invalid document reader",
            "plan_rationale": "The first step tried to write text from documents.",
            "steps": [
                {
                    "name": "Write summary",
                    "instructions": "Write a summary directly from uploaded documents.",
                }
            ],
        },
        tool_call_id="call-assembly-rejection",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is None
    assert result.failure_kind == "validation"
    assert result.failure_codes == frozenset(
        {"assembly_source_file_first_step_requires_json"}
    )
    assert result.feedback is not None
    assert "first semantic step" in result.feedback

    corrected = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[
            ConversationMessage(role="user", content="Bygg ett dokumentflöde.")
        ],
        arguments={
            "flow_name": "Corrected document reader",
            "plan_rationale": "Read the document before writing the summary.",
            "steps": [
                {
                    "name": "Read document",
                    "instructions": "Extract source-grounded facts.",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Source-grounded summary.",
                        }
                    ],
                },
                {
                    "name": "Write summary",
                    "instructions": "Write a summary from the extracted facts.",
                },
            ],
        },
        tool_call_id="call-corrected-assembly",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert corrected.failure_kind is None
    assert corrected.compiled_proposal is not None
    assert corrected.compiled_proposal.validation.valid


@pytest.mark.parametrize(
    ("failure_code", "retryable"),
    [
        ("assembly_plan_invariant_failed", False),
        ("invalid_structured_underlag_projection", False),
        ("assembly_source_file_first_step_requires_json", True),
    ],
)
@pytest.mark.asyncio
async def test_process_create_intent_arguments_only_returns_retryable_architecture_feedback(
    failure_code: str,
    retryable: bool,
) -> None:
    error = AIBuilderArchitectureError(
        public_code="architecture_materialization_failed",
        detail="The proposed architecture could not be compiled.",
        log_context={"failure_code": failure_code},
    )
    arguments = {
        "flow_name": "Architecture classification",
        "plan_rationale": "Exercise architecture failure ownership.",
        "steps": [
            {
                "name": "Summarize",
                "instructions": "Summarize the supplied text.",
            }
        ],
    }

    with patch(
        "eneo.flows.ai_builder.ai_builder_create_proposal."
        "compile_create_intent_to_spec",
        side_effect=error,
    ):
        if not retryable:
            with pytest.raises(AIBuilderArchitectureError) as exc_info:
                await _process_create_intent_arguments(
                    turn=_make_turn(),
                    conversation=[],
                    arguments=arguments,
                    tool_call_id="call-architecture-classification",
                    available_model_refs=None,
                    available_kb_refs=None,
                )

            assert exc_info.value is error
            return

        result = await _process_create_intent_arguments(
            turn=_make_turn(),
            conversation=[],
            arguments=arguments,
            tool_call_id="call-architecture-classification",
            available_model_refs=None,
            available_kb_refs=None,
        )

    assert result.compiled_proposal is None
    assert result.feedback == error.detail
    assert result.failure_kind == "validation"
    assert result.failure_codes == frozenset({failure_code})


@pytest.mark.asyncio
async def test_corrupt_report_context_fails_closed_without_model_repair() -> None:
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="text",
                    output_type="pdf",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["text_to_artifact_report"],
            aggregation_intent="aggregate",
            report_disposition="both",
        )
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        await process_create_intent_arguments(
            turn=_make_turn(),
            conversation=[
                ConversationMessage(
                    role="user",
                    content="Build a PDF report from the supplied text.",
                )
            ],
            arguments={
                "flow_name": "Corrupt report context",
                "plan_rationale": "Write and render the report.",
                "steps": [
                    {
                        "name": "Write report",
                        "instructions": "Write the report from the supplied text.",
                    }
                ],
            },
            tool_call_id="call-corrupt-report-context",
            available_model_refs=None,
            available_kb_refs=None,
            planning_state=state,
        )

    assert exc_info.value.log_context["failure_code"] == (
        "assembly_document_report_compose_topology_missing"
    )


@pytest.mark.asyncio
async def test_report_citations_degrade_to_one_user_visible_warning() -> None:
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="pdf",
                    output_mode="render_verbatim",
                )
            ],
            chosen_patterns=["document_to_pdf_report"],
            aggregation_intent="linear",
            report_disposition="both",
        )
    )

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[
            ConversationMessage(
                role="user",
                content="Build a cited PDF report from each uploaded document.",
                metadata={"ui_language": "sv"},
            )
        ],
        arguments={
            "flow_name": "Cited source report",
            "plan_rationale": "Write and render the cited report.",
            "steps": [
                {
                    "name": "Write cited report",
                    "instructions": "Write the report with citations.",
                    "citations_requested": True,
                }
            ],
        },
        tool_call_id="call-cited-report",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is not None
    compiled = result.compiled_proposal
    assert all(
        step.output_config != {"citation_mode": "inline_inref_sidecar"}
        for step in compiled.content.spec.steps
    )
    warnings = [
        warning
        for warning in compiled.validation.warnings
        if warning.code == "citation_mode_unsupported"
    ]
    assert len(warnings) == 1
    assert warnings[0].message == (
        "Källhänvisningar inaktiverades eftersom resultatet inte kan innehålla "
        "infogade källhänvisningar."
    )

    stored = build_flow_builder_proposal(compiled)
    assert [
        (warning.code, warning.severity.value)
        for warning in stored.content.lint_warnings
    ] == [("citation_mode_unsupported", "warning")]


@pytest.mark.asyncio
async def test_combined_report_models_surface_warning_on_stored_plan() -> None:
    state = PlanningState.empty()
    state.mapped_file_limit = MappedFileLimit(
        proposed_value=4,
        accepted_value=4,
        provenance="authored",
    )
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="pdf",
                    output_mode="render_verbatim",
                )
            ],
            chosen_patterns=["document_to_pdf_report"],
            aggregation_intent="linear",
            report_disposition="synthesized_overview",
        )
    )

    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource("draft-model-id", "draft"),
            _model_resource("body-model-id", "body"),
        ],
        available_kbs=[],
    )
    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[
            ConversationMessage(
                role="user",
                content="Use the selected models to build the source report.",
                metadata={"ui_language": "sv"},
            )
        ],
        arguments={
            "flow_name": "Model-specific source report",
            "plan_rationale": "Extract evidence and write the final report.",
            "steps": [
                {
                    "name": "Read source",
                    "instructions": "Extract source evidence.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "Source evidence.",
                            "children": [
                                {
                                    "name": "summary",
                                    "field_type": "string",
                                    "description": "Source summary.",
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "Draft report",
                    "instructions": "Draft the report.",
                    "model_ref": "model.draft",
                },
                {
                    "name": "Compose report",
                    "instructions": "Compose the final report.",
                    "model_ref": "model.body",
                },
            ],
        },
        tool_call_id="call-combined-report-models",
        available_model_refs=catalog.model_refs,
        available_kb_refs=None,
        resource_catalog=catalog,
        planning_state=state,
    )

    assert result.compiled_proposal is not None
    compiled = result.compiled_proposal
    assert compiled.content.spec.steps[1].assistant_spec.model_ref == "model.body"
    warnings = [
        warning
        for warning in compiled.validation.warnings
        if warning.code == "document_report_model_selection_combined"
    ]
    assert len(warnings) == 1
    assert warnings[0].message == (
        "Stegen angav olika modellval; de kombinerades och det kombinerade "
        "rapportskrivningssteget använder modellvalet model.body."
    )

    stored = build_flow_builder_proposal(compiled)
    assert [
        (warning.code, warning.severity.value)
        for warning in stored.content.lint_warnings
    ] == [("document_report_model_selection_combined", "warning")]


@pytest.mark.asyncio
async def test_outline_audio_to_docx_returns_compiled_proposal() -> None:
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="docx",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=[
                "audio_to_artifact_report",
                "form_field_runtime_inputs",
            ],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )
    state.resolved_slots["runtime_metadata_fields"] = ResolvedSlot(
        name="runtime_metadata_fields",
        value=DETAILED_RUNTIME_METADATA,
        source="structured_answer",
        confidence="high",
    )
    state.input_fields = [
        ConfirmedRuntimeMetadataField(
            value=FlowInputFieldIntent(
                variable_name="arendenummer",
                label="Ärendenummer",
                provenance="user_confirmed",
            ),
            purpose="shape_result",
            structured_answer_message_id="message-runtime-fields",
        ),
        ConfirmedRuntimeMetadataField(
            value=FlowInputFieldIntent(
                variable_name="handlaggare",
                label="Handläggare",
                provenance="user_confirmed",
            ),
            purpose="shape_result",
            structured_answer_message_id="message-runtime-fields",
        ),
    ]
    state.checkpoint_intents = [
        CheckpointIntent(
            evidence_level="explicit",
            producer_kind="structured_result",
            operation="set",
            mode=FlowStepReviewMode.EDIT,
            confidence="high",
            evidence=["quote:user_message:1:Edit the extracted facts."],
        )
    ]

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som transkriberar ljud och skapar DOCX. "
                    "Användaren ska fylla i ärendenummer och handläggare vid körning."
                ),
            )
        ],
        arguments={
            "flow_name": "Ljudrapport",
            "plan_rationale": "Skapa en DOCX-rapport från uppladdat ljud.",
            "steps": [
                {
                    "name": "Analysera inspelningen",
                    "instructions": "Extrahera sakuppgifter ur transkriptionen.",
                    "output_fields": [
                        {
                            "name": "sakuppgifter",
                            "field_type": "string",
                            "description": "Sakuppgifter ur inspelningen.",
                        }
                    ],
                },
                {
                    "name": "Skriv rapporten",
                    "instructions": "Skriv rapporten från sakuppgifterna.",
                },
            ],
        },
        tool_call_id="call-audio-docx",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is not None
    spec = result.compiled_proposal.content.spec
    assert [field.name for field in spec.form_fields or ()] == [
        "arendenummer",
        "handlaggare",
    ]
    assert spec.steps[0].input_type == InputType.AUDIO
    analysis_step = spec.steps[1]
    report_step = spec.steps[2]
    assert analysis_step.review_policy is not None
    assert analysis_step.review_policy.mode.value == "edit"
    assert report_step.input_bindings is not None
    assert "{{ flow_input.arendenummer }}" in str(report_step.input_bindings)
    assert "{{ flow_input.handlaggare }}" in str(report_step.input_bindings)
    assert spec.steps[-1].output_type == OutputType.DOCX
    assert spec.steps[-1].output_mode == OutputMode.RENDER_VERBATIM
    await assert_create_spec_prepares_through_authoring_command_async(spec)


@pytest.mark.asyncio
async def test_outline_processing_uses_confirmed_planning_state_field() -> None:
    state = PlanningState.empty()
    state.resolved_slots = {
        "runtime_metadata_fields": ResolvedSlot(
            name="runtime_metadata_fields",
            value=DETAILED_RUNTIME_METADATA,
            source="structured_answer",
            confidence="high",
        ),
    }
    state.input_fields = [
        ConfirmedRuntimeMetadataField(
            value=FlowInputFieldIntent(
                variable_name="malgrupp",
                label="Målgrupp",
                provenance="user_confirmed",
            ),
            purpose="whole_flow",
            structured_answer_message_id="message-runtime-fields",
        )
    ]

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som använder inmatningsfält för målgrupp "
                    "vid körning och skriver en rapport."
                ),
            )
        ],
        arguments={
            "flow_name": "Målgruppsrapport",
            "plan_rationale": "Anpassa rapporten efter målgrupp.",
            "steps": [
                {
                    "name": "Skriv rapport",
                    "instructions": "Skriv rapporten för vald målgrupp.",
                }
            ],
        },
        tool_call_id="call-runtime-hints",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is not None
    spec = result.compiled_proposal.content.spec
    assert spec.form_fields is not None
    assert [field.name for field in spec.form_fields] == ["malgrupp"]
    assert spec.steps[0].input_bindings is not None
    assert "{{ flow_input.malgrupp }}" in spec.steps[0].input_bindings["question"]
    await assert_create_spec_prepares_through_authoring_command_async(spec)


@pytest.mark.asyncio
async def test_unstructured_field_text_does_not_create_hidden_server_contract() -> None:
    state = PlanningState.empty()
    state.resolved_slots["runtime_metadata_fields"] = ResolvedSlot(
        name="runtime_metadata_fields",
        value=DETAILED_RUNTIME_METADATA,
        source="heuristic",
        confidence="high",
    )

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde där användaren fyller i ärendenummer och "
                    "handläggare vid körning."
                ),
            )
        ],
        arguments={
            "flow_name": "Ärendesammanfattning",
            "plan_rationale": "Sammanfatta ärendet.",
            "steps": [
                {
                    "name": "Sammanfatta ärendet",
                    "instructions": "Skriv en tydlig sammanfattning.",
                }
            ],
        },
        tool_call_id="call-no-hidden-field-contract",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is not None
    assert result.compiled_proposal.content.spec.form_fields is None


@pytest.mark.asyncio
async def test_confirmed_create_field_preserves_options_and_provenance() -> None:
    state = PlanningState.empty()
    state.input_fields = [
        ConfirmedRuntimeMetadataField(
            value=FlowInputFieldIntent(
                variable_name="priority",
                label="Priority",
                field_type="select",
                required=True,
                options=["Low", "High"],
                provenance="user_confirmed",
            ),
            purpose="interpret_input",
            structured_answer_message_id="message-runtime-fields",
        )
    ]

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[],
        arguments={
            "flow_name": "Priority response",
            "plan_rationale": "Use the confirmed priority when drafting.",
            "steps": [
                {
                    "name": "Draft response",
                    "instructions": "Draft a response for the selected priority.",
                }
            ],
        },
        tool_call_id="call-confirmed-field",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is not None
    fields = result.compiled_proposal.content.spec.form_fields
    assert fields is not None
    assert fields[0].model_dump(exclude_none=True) == {
        "name": "priority",
        "label": "Priority",
        "type": "select",
        "required": True,
        "options": ["Low", "High"],
    }
    assert result.compiled_proposal.content.lint_warnings == []
    assert state.input_fields[0].value.provenance == "user_confirmed"
    stored_proposal = build_flow_builder_proposal(result.compiled_proposal)
    assert stored_proposal.content.spec.form_fields == fields


@pytest.mark.asyncio
async def test_confirmed_create_shadow_field_is_rejected_explicitly() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = ResolvedSlot(
        name="primary_runtime_input",
        value="text",
        source="structured_answer",
        confidence="high",
    )
    state.input_fields = [
        ConfirmedRuntimeMetadataField(
            value=FlowInputFieldIntent(
                variable_name="text",
                label="Text",
                provenance="user_confirmed",
            ),
            purpose="interpret_input",
            structured_answer_message_id="message-runtime-fields",
        )
    ]

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[],
        arguments={
            "flow_name": "Text summary",
            "plan_rationale": "Summarize the primary text.",
            "steps": [
                {
                    "name": "Summarize",
                    "instructions": "Summarize the text.",
                }
            ],
        },
        tool_call_id="call-confirmed-shadow-field",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is None
    assert result.failure_kind == "validation"
    assert result.failure_codes == frozenset({"confirmed_form_field_incompatible"})


@pytest.mark.asyncio
async def test_confirmed_source_output_collision_is_model_repairable() -> None:
    result = await _process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[],
        arguments={
            "flow_name": "Document case summary",
            "plan_rationale": "Extract and summarize the case.",
            "steps": [
                {
                    "name": "Extract source facts",
                    "instructions": "Extract the case id from the document.",
                    "output_fields": [
                        {
                            "name": "case_id",
                            "field_type": "string",
                            "description": "Case id found in the source.",
                        }
                    ],
                },
                {
                    "name": "Write summary",
                    "instructions": "Write the final summary.",
                },
            ],
        },
        tool_call_id="call-source-output-collision",
        available_model_refs=None,
        available_kb_refs=None,
        compile_context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            runtime_input_fields=(
                ConfirmedRuntimeMetadataField(
                    value=FlowInputFieldIntent(
                        variable_name="case_id",
                        label="Case id",
                        provenance="user_confirmed",
                    ),
                    purpose="shape_result",
                    structured_answer_message_id="message-runtime-fields",
                ),
            ),
        ),
    )

    assert result.compiled_proposal is None
    assert result.failure_kind == "validation"
    assert result.failure_codes == frozenset(
        {"confirmed_runtime_input_source_output_collision"}
    )
    assert result.feedback is not None
    assert "case_id" in result.feedback
