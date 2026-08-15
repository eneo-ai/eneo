from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import cast
from uuid import UUID, uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_create_compile_context import (
    CreateCompileContext,
    create_compile_context_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    compile_create_intent_to_spec,
)
from eneo.flows.ai_builder.ai_builder_critic_invariants import (
    evaluate_critic_invariants,
)
from eneo.flows.ai_builder.ai_builder_json_schema_paths import (
    schema_leaf_property_names,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    RequestedOutputSections,
    extract_requested_output_sections,
)
from eneo.flows.ai_builder.ai_builder_plan_quality_critic import (
    build_conversation_critic_context,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    FlowInputFieldIntent,
    ProposalIntentArgumentError,
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_result_contract import (
    ResultObligation,
    ResultOutputFieldRole,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_fields import (
    RuntimeInputFieldHint,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    build_schema_evidence,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import SourceCaptureField
from eneo.flows.ai_builder.ai_builder_template_attachment_contract import (
    apply_template_attachment_contract,
)
from eneo.flows.ai_builder.ai_builder_validator import validate_spec
from eneo.flows.ai_builder.pattern_registry import (
    EXTRACT_TEMPLATE_VARIABLES_STEP,
    FLOW_INPUT_AUDIO_TRANSCRIPTION,
    FLOW_INPUT_DOCUMENT_UPLOAD,
    PREPARE_TEMPLATE_CONTENT_STEP,
    TEMPLATE_FILL_DOCX_STEP,
    TERMINAL_ARTIFACT_STEP,
)
from eneo.flows.ai_builder.planning_state import (
    AggregationIntent,
    CheckpointIntent,
    ConfirmedRuntimeMetadataField,
    ExampleOutputCitation,
    ExampleOutputConstraintEvidence,
    ExampleOutputSchemaInferenceOutcome,
    ExampleOutputSourceCoverage,
    FileRoleEvidence,
    MappedFileLimit,
    NamedResultEvidence,
    PlanningSignal,
    PlanningState,
    ReportDisposition,
    ResolvedSlot,
    RuntimeMetadataFieldPurpose,
    SchemaResolution,
)
from eneo.flows.flow_authoring_spec import (
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode
from eneo.flows.input_binding_contract_rules import (
    effective_question_binding,
    item_template_field_names,
    source_ref_bindings,
)
from eneo.flows.runtime.step_definition_parser import parse_runtime_steps
from eneo.json_types import JsonObject


def _question(input_bindings: dict[str, object] | None) -> str:
    question = effective_question_binding(input_bindings)
    assert question is not None
    return question


def _slot(name: str, value: str) -> ResolvedSlot:
    return ResolvedSlot(
        name=name,
        value=value,
        source="structured_answer",
        confidence="high",
    )


def _confirmed_runtime_field(
    variable_name: str,
    label: str,
    *,
    purpose: RuntimeMetadataFieldPurpose = "interpret_input",
    required: bool = False,
) -> ConfirmedRuntimeMetadataField:
    return ConfirmedRuntimeMetadataField(
        value=FlowInputFieldIntent(
            variable_name=variable_name,
            label=label,
            required=required,
            provenance="user_confirmed",
        ),
        purpose=purpose,
        structured_answer_message_id="message-1",
    )


def _commit_architecture(state: PlanningState) -> None:
    draft = derive_architecture_commit_draft(state)
    assert draft is not None
    state.architecture_commit = finalize_architecture_commit(
        draft,
        now=lambda: datetime(2026, 8, 2, tzinfo=timezone.utc),
    )


def test_compile_context_bridges_flow_input_type_to_authoring_input_type() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "documents",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_text",
    )
    _commit_architecture(state)

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.runtime_input_type == InputType.DOCUMENT
    assert context.final_output_type == OutputType.TEXT


def test_compile_context_defaults_missing_runtime_architecture_to_text() -> None:
    context = CreateCompileContext()

    assert context.effective_runtime_input_type is InputType.TEXT


def test_compile_context_does_not_derive_uncommitted_architecture() -> None:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "documents"),
        "terminal_output": _slot("terminal_output", "structured_text"),
    }

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.runtime_input_type is None
    assert context.final_output_type is None
    assert context.pattern_ids == ()


def test_compile_context_keeps_template_placeholder_evidence_out_of_terminal_schema() -> (
    None
):
    state = PlanningState.empty()
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "docx_document",
    )
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "documents",
    )
    state.resolved_slots["document_material_scope"] = _slot(
        "document_material_scope",
        "single_document_case",
    )
    state.resolved_slots["docx_output_mode"] = _slot(
        "docx_output_mode",
        "template_fill_docx",
    )
    _commit_architecture(state)
    state.output_schema_evidence = build_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {"kundnamn": {"type": "string"}},
        },
        source="template_placeholders",
        source_file_ids=("00000000-0000-0000-0000-000000000001",),
        confidence="high",
        evidence=["file:file_id:content:template_placeholder:kundnamn"],
    )

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.final_output_type == OutputType.DOCX
    assert context.terminal_output_schema is None
    assert [
        hint.variable_name for hint in context.template_placeholder_field_hints
    ] == ["kundnamn"]


def test_policy_default_does_not_override_confirmed_runtime_fields() -> None:
    state = PlanningState.empty()
    state.resolved_slots["runtime_metadata_fields"] = ResolvedSlot(
        name="runtime_metadata_fields",
        value="no_extra_metadata",
        source="policy_default",
        confidence="high",
    )
    state.input_fields = [_confirmed_runtime_field("case_type", "Case type")]
    context = create_compile_context_from_planning_state(state)
    assert context is not None
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Case routing",
            "plan_rationale": "Route the case using its confirmed type.",
            "steps": [
                {
                    "name": "Route case",
                    "instructions": "Route the case using its type.",
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(intent, context=context)

    assert [field.name for field in compiled.form_fields or ()] == ["case_type"]
    assert "{{ flow_input.case_type }}" in _question(compiled.steps[0].input_bindings)


def test_compile_context_keeps_distinct_long_template_placeholder_names() -> None:
    shared_prefix = "a" * 80
    first = f"{shared_prefix}_first"
    second = f"{shared_prefix}_second"
    state = PlanningState.empty()
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "docx_document",
    )
    state.output_schema_evidence = build_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {
                first: {"type": "string"},
                second: {"type": "string"},
            },
        },
        source="template_placeholders",
        source_file_ids=("00000000-0000-0000-0000-000000000001",),
        confidence="high",
        evidence=[
            f"file:file_id:content:template_placeholder:{first}",
            f"file:file_id:content:template_placeholder:{second}",
        ],
    )

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert [
        hint.variable_name for hint in context.template_placeholder_field_hints
    ] == [first, second]


def test_compile_context_binds_declared_output_schema_to_json_terminal() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "text",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_json",
    )
    _commit_architecture(state)
    schema: JsonObject = {
        "type": "object",
        "properties": {"decision": {"type": "string"}},
        "required": ["decision"],
    }
    state.output_schema_evidence = build_schema_evidence(
        json_schema=schema,
        source="declared_schema",
        source_file_ids=("00000000-0000-0000-0000-000000000001",),
        confidence="high",
        evidence=["file:00000000-0000-0000-0000-000000000701:json_schema_attachment"],
    )

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.final_output_type == OutputType.JSON
    assert context.terminal_output_schema == schema


def test_compile_context_binds_declared_input_schema_to_json_flow_input() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "json",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_json",
    )
    _commit_architecture(state)
    schema: JsonObject = {
        "type": "object",
        "properties": {"case_id": {"type": "string"}},
        "required": ["case_id"],
    }
    state.input_schema_evidence = build_schema_evidence(
        json_schema=schema,
        source="declared_schema",
        source_file_ids=("00000000-0000-0000-0000-000000000001",),
        confidence="high",
        evidence=["file:00000000-0000-0000-0000-000000000701:json_schema_attachment"],
    )

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.runtime_input_type == InputType.JSON
    assert context.flow_input_schema == schema


def test_compiler_applies_distinct_input_and_output_schema_evidence() -> None:
    input_schema: JsonObject = {
        "type": "object",
        "properties": {"case_id": {"type": "string"}},
        "required": ["case_id"],
    }
    output_schema: JsonObject = {
        "type": "object",
        "properties": {"decision": {"type": "string"}},
        "required": ["decision"],
    }
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "json",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "structured_json",
    )
    _commit_architecture(state)
    state.input_schema_evidence = build_schema_evidence(
        json_schema=input_schema,
        source="declared_schema",
        source_file_ids=("00000000-0000-0000-0000-000000000001",),
        confidence="high",
        evidence=["file:00000000-0000-0000-0000-000000000701:input_schema"],
    )
    state.output_schema_evidence = build_schema_evidence(
        json_schema=output_schema,
        source="declared_schema",
        source_file_ids=("00000000-0000-0000-0000-000000000002",),
        confidence="high",
        evidence=["file:00000000-0000-0000-0000-000000000702:output_schema"],
    )
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Normalize case JSON",
            "plan_rationale": "Validate the input and return a decision.",
            "steps": [
                {
                    "name": "Normalize case input",
                    "instructions": "Validate the case identifier for processing.",
                    "output_fields": [
                        {
                            "name": "case_id",
                            "field_type": "string",
                            "description": "Validated case identifier.",
                        }
                    ],
                },
                {
                    "name": "Decide case",
                    "instructions": "Return the decision for the validated case.",
                },
            ],
        }
    )

    context = create_compile_context_from_planning_state(state)
    assert context is not None
    compiled = compile_create_intent_to_spec(intent, context=context)

    assert len(compiled.steps) == 2
    assert compiled.steps[0].input_contract == input_schema
    assert compiled.steps[0].input_bindings is None
    assert compiled.steps[1].input_source is InputSource.PREVIOUS_STEP
    assert compiled.steps[1].input_contract == compiled.steps[0].output_contract
    assert compiled.steps[1].input_contract != input_schema
    assert compiled.steps[1].output_contract == output_schema
    validation = validate_spec(compiled)
    assert validation.valid, validation.errors


def test_related_document_package_keeps_named_results_as_hints() -> None:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "documents"),
        "document_material_scope": _slot(
            "document_material_scope",
            "multiple_documents_case",
        ),
        "terminal_output": _slot("terminal_output", "structured_json"),
    }
    _commit_architecture(state)
    state.named_result_evidence = [
        NamedResultEvidence(
            name=name,
            confidence="high",
            evidence=[f"quote:user_message:application:field:{name}"],
        )
        for name in ("candidate_name", "qualification_summary")
    ]
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Application summary",
            "plan_rationale": "Read the related application documents once.",
            "steps": [
                {
                    "name": "Summarize application",
                    "instructions": (
                        "Read the application package and return the requested fields."
                    ),
                    "output_fields": [
                        {
                            "name": "candidate_name",
                            "field_type": "string",
                            "description": "Kandidatens namn.",
                            "required": True,
                        },
                        {
                            "name": "qualification_summary",
                            "field_type": "string",
                            "description": "Sammanfattning av meriter.",
                            "required": True,
                        },
                    ],
                }
            ],
        }
    )

    context = create_compile_context_from_planning_state(state)
    assert context is not None
    assert context.aggregation_intent == "linear"
    # Named results are hints: the proposal owns types; nothing is pinned.
    assert context.terminal_output_schema is None

    compiled = compile_create_intent_to_spec(intent, context=context)

    assert len(compiled.steps) == 1
    assert compiled.steps[0].input_source is InputSource.FLOW_INPUT
    assert compiled.steps[0].input_type is InputType.DOCUMENT
    contract_names = set(schema_leaf_property_names(compiled.steps[0].output_contract))
    assert {"candidate_name", "qualification_summary"} <= contract_names
    assert validate_spec(compiled).valid


def test_compile_context_rejects_input_schema_for_non_json_runtime_input() -> None:
    with pytest.raises(ValueError, match="requires JSON runtime input"):
        CreateCompileContext(
            runtime_input_type=InputType.TEXT,
            flow_input_schema={"type": "object"},
        )


def test_compiler_rejects_input_schema_with_composite_flow_input_bindings() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Normalize case JSON",
            "plan_rationale": "Use the runtime JSON and the selected case type.",
            "steps": [
                {
                    "name": "Normalize case",
                    "instructions": "Validate the case for the selected case type.",
                }
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            intent,
            context=CreateCompileContext(
                runtime_input_type=InputType.JSON,
                final_output_type=OutputType.JSON,
                flow_input_schema={
                    "type": "object",
                    "properties": {"case_id": {"type": "string"}},
                },
                runtime_input_fields=(
                    _confirmed_runtime_field("case_type", "Case type", required=True),
                ),
            ),
        )

    assert exc_info.value.log_context["failure_code"] == (
        "flow_input_schema_composite_bindings_unsupported"
    )


@pytest.mark.parametrize("pattern_ids", [(), ("json_to_text_summary",)])
def test_compiler_rejects_json_to_text_architecture(
    pattern_ids: tuple[str, ...],
) -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Summarize case JSON",
            "plan_rationale": "Summarize the structured case input.",
            "steps": [
                {
                    "name": "Summarize case",
                    "instructions": "Write a concise case summary.",
                }
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            intent,
            context=CreateCompileContext(
                runtime_input_type=InputType.JSON,
                final_output_type=OutputType.TEXT,
                final_output_mode=OutputMode.PASS_THROUGH,
                pattern_ids=pattern_ids,
            ),
        )

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.log_context["failure_code"] == (
        "assembly_unsupported_runtime_output_tuple"
    )


def test_compile_context_binds_inferred_example_as_an_open_json_shape() -> None:
    file_id = UUID("00000000-0000-0000-0000-000000000714")
    schema: JsonObject = {
        "type": "object",
        "properties": {"decision": {"type": "string"}},
    }
    state = PlanningState.model_validate(
        {
            **dict(PlanningState.empty()),
            "resolved_slots": {
                "primary_runtime_input": _slot(
                    "primary_runtime_input",
                    "text",
                ),
                "terminal_output": _slot(
                    "terminal_output",
                    "structured_json",
                ),
            },
            "file_roles": [
                FileRoleEvidence(
                    file_id=file_id,
                    filename="expected.json",
                    file_type="text",
                    mimetype="application/json",
                    has_readable_text=True,
                    coverage="fully_seen",
                    role="example_output",
                    source="model",
                    confidence="medium",
                )
            ],
            "example_output_constraints": ExampleOutputConstraintEvidence(
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
                        source_id=f"uploaded_file:{file_id}",
                        file_id=file_id,
                        quote='"decision": "approved"',
                    )
                ],
            ),
            "schema_resolution": SchemaResolution.from_evidence(
                input_evidence=None,
                output_evidence=build_schema_evidence(
                    json_schema=schema,
                    source="inferred_example",
                    source_file_ids=(file_id,),
                    confidence="medium",
                    evidence=(f"file:{file_id}:inferred_example_shape",),
                ),
            ),
            "example_output_schema_inference": ExampleOutputSchemaInferenceOutcome(
                status="inferred",
                source_file_ids=[file_id],
            ),
        }
    )
    _commit_architecture(state)

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    # Inferred examples are open hints; the proposal owns the contract.
    assert context.terminal_output_schema is None


def test_compile_context_keeps_input_schema_out_of_docx_terminal() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "json",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "docx_document",
    )
    state.resolved_slots["docx_output_mode"] = _slot(
        "docx_output_mode",
        "generated_docx",
    )
    _commit_architecture(state)
    state.input_schema_evidence = build_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {"decision": {"type": "string"}},
        },
        source="declared_schema",
        source_file_ids=("00000000-0000-0000-0000-000000000001",),
        confidence="high",
        evidence=["file:00000000-0000-0000-0000-000000000701:json_schema_attachment"],
    )

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.final_output_type is OutputType.DOCX
    assert context.terminal_output_schema is None


def test_compile_context_requires_only_summary_source_reader_obligation() -> None:
    state = PlanningState.empty()
    state.resolved_slots["post_processing_goal"] = _slot(
        "post_processing_goal",
        "structure_key_information",
    )
    state.signals.append(
        PlanningSignal(
            question_id="result_obligation",
            value="summary",
            confidence="high",
            source="model",
        )
    )

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert [field.name for field in context.source_reader_required_fields] == [
        "summary"
    ]


def test_compile_context_does_not_turn_report_obligations_into_reader_fields() -> None:
    state = PlanningState.empty()
    state.resolved_slots["post_processing_goal"] = _slot(
        "post_processing_goal",
        "action_followup",
    )
    state.signals.append(
        PlanningSignal(
            question_id="result_obligation",
            value="owners",
            confidence="high",
            source="model",
        )
    )
    state.signals.append(
        PlanningSignal(
            question_id="result_obligation",
            value="deadlines",
            confidence="high",
            source="model",
        )
    )

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.source_reader_required_fields == ()
    assert [field.name for field in context.result_contract_output_fields] == [
        "decisions",
        "actions",
        "owners",
        "deadlines",
        "open_questions",
    ]


def test_compile_context_derives_analysis_fields_from_result_obligations() -> None:
    state = PlanningState.empty()
    state.resolved_slots["post_processing_goal"] = _slot(
        "post_processing_goal",
        "compare_or_validate",
    )
    state.signals.extend(
        [
            PlanningSignal(
                question_id="result_obligation",
                value="missing_information_policy",
                confidence="high",
                source="model",
            ),
            PlanningSignal(
                question_id="result_obligation",
                value="recommendations",
                confidence="high",
                source="model",
            ),
        ]
    )

    context = create_compile_context_from_planning_state(state, ui_language="sv")

    assert context is not None
    assert [field.name for field in context.result_contract_output_fields] == [
        "matches",
        "missing_information",
        "uncertainty",
        "recommended_action",
    ]
    assert context.source_reader_required_fields == ()


def test_compile_context_reads_report_disposition_only_from_commit() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "documents",
    )
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "pdf_document",
    )
    state.resolved_slots["pdf_generation_mode"] = _slot(
        "pdf_generation_mode",
        "generated_pdf",
    )
    state.resolved_slots["document_material_scope"] = _slot(
        "document_material_scope",
        "multiple_documents_case",
    )
    state.resolved_slots["report_disposition"] = _slot(
        "report_disposition",
        "per_source_sections",
    )
    _commit_architecture(state)
    state.resolved_slots["report_disposition"] = _slot(
        "report_disposition",
        "both",
    )

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.report_disposition == "per_source_sections"


def test_compiler_uses_assembly_path_for_single_step_linear_flow() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Quick answer",
            "flow_description": "Answer with the requested tone.",
            "plan_rationale": "One text step is enough.",
            "steps": [
                {
                    "name": "Write answer",
                    "instructions": "Write the answer in the requested tone.",
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_fields=(
                _confirmed_runtime_field("tone", "Tone", required=True),
            ),
        ),
    )

    assert compiled.flow_name == "Quick answer"
    assert compiled.flow_description == "Answer with the requested tone."
    assert compiled.form_fields is not None
    assert [field.name for field in compiled.form_fields] == ["tone"]
    assert len(compiled.steps) == 1
    step = compiled.steps[0]
    assert step.input_source == InputSource.FLOW_INPUT
    assert step.input_type == InputType.TEXT
    assert step.output_type == OutputType.TEXT
    assert step.output_mode == OutputMode.PASS_THROUGH
    assert _question(step.input_bindings) == (
        "{{ indata_text }}\n\ntone: {{ flow_input.tone }}"
    )
    assert validate_spec(compiled).valid


def test_assembly_plan_value_error_becomes_typed_architecture_failure() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Text report",
            "plan_rationale": "A plain text step cannot satisfy reader fields.",
            "steps": [
                {
                    "name": "Write report",
                    "instructions": "Write the report.",
                }
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            intent,
            context=CreateCompileContext(
                source_reader_required_fields=(
                    SourceCaptureField(
                        name="document_title",
                        description="Document title.",
                    ),
                ),
            ),
        )

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.log_context["failure_code"] == (
        "assembly_plan_invariant_failed"
    )
    assert "source_reader_required_fields require a source-reader planned step" in (
        exc_info.value.detail
    )


def test_audio_input_translates_source_reader_obligation_instead_of_dead_ending() -> (
    None
):
    # A source reader only exists for document/file/text runtime input. When
    # the slot classifier derives a capture obligation but the session's
    # runtime input is audio, no step arrangement can ever satisfy the
    # assembly invariant — the planner would burn every repair attempt on a
    # constraint it does not control. The compiler must keep the flow
    # buildable AND carry the obligation as server-owned terminal-step
    # instructions, independent of how the model worded its intent.
    # Mirrors the production failure: audio in, DOCX out, obligation
    # "summary" from the planning state, and an intent that never mentions
    # summarization.
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Beslutsunderlag från möte",
            "plan_rationale": "Transkribera och sammanställ.",
            "steps": [
                {
                    "name": "Skriv beslutsunderlag",
                    "instructions": "Sammanställ transkriptet till ett beslutsunderlag.",
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.AUDIO,
            final_output_type=OutputType.DOCX,
            source_reader_required_fields=(
                SourceCaptureField(
                    name="summary",
                    description="Kort sammanfattning grundad i källmaterialet.",
                ),
            ),
        ),
    )

    # The exact production topology: transcribe → write → render DOCX.
    assert [
        (step.input_type, step.output_type, step.output_mode) for step in compiled.steps
    ] == [
        (InputType.AUDIO, OutputType.TEXT, OutputMode.TRANSCRIBE_ONLY),
        (InputType.TEXT, OutputType.TEXT, OutputMode.PASS_THROUGH),
        (InputType.TEXT, OutputType.DOCX, OutputMode.RENDER_VERBATIM),
    ]
    # The obligation survives as a deterministic server-owned instruction on
    # the writer step even though the intent never mentioned a summary.
    writer_step = compiled.steps[1]
    assert "sammanfattning" in writer_step.assistant_spec.instructions.lower()
    assert validate_spec(compiled).valid


def test_translated_obligation_survives_dropped_terminal_render_helper() -> None:
    # When the model's intent ends with an explicit "create the DOCX" helper,
    # assembly drops that helper during normalization. The server-owned
    # obligation must land on the RETAINED content producer — never on the
    # helper that is about to disappear.
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Beslutsunderlag från möte",
            "plan_rationale": "Transkribera, sammanställ och skapa dokumentet.",
            "steps": [
                {
                    "name": "Skriv beslutsunderlag",
                    "instructions": "Sammanställ transkriptet till ett beslutsunderlag.",
                },
                {
                    "name": "Skapa DOCX",
                    "instructions": "Skapa DOCX-dokumentet.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.AUDIO,
            final_output_type=OutputType.DOCX,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            source_reader_required_fields=(
                SourceCaptureField(
                    name="summary",
                    description="Kort sammanfattning grundad i källmaterialet.",
                ),
            ),
        ),
    )

    assert [
        (step.input_type, step.output_type, step.output_mode) for step in compiled.steps
    ] == [
        (InputType.AUDIO, OutputType.TEXT, OutputMode.TRANSCRIBE_ONLY),
        (InputType.TEXT, OutputType.TEXT, OutputMode.PASS_THROUGH),
        (InputType.TEXT, OutputType.DOCX, OutputMode.RENDER_VERBATIM),
    ]
    writer_step = compiled.steps[1]
    renderer_step = compiled.steps[2]
    assert "sammanfattning" in writer_step.assistant_spec.instructions.lower()
    assert "sammanfattning" not in renderer_step.assistant_spec.instructions.lower()
    assert validate_spec(compiled).valid


@pytest.mark.parametrize(
    ("report_disposition", "expected_contract_fields"),
    [
        ("per_source_sections", {"source_sections"}),
        ("synthesized_overview", {"report_title", "overall_overview"}),
        (
            "both",
            {"source_sections", "report_title", "overall_overview"},
        ),
    ],
)
def test_committed_report_disposition_lowers_minimal_semantic_intent(
    report_disposition: ReportDisposition,
    expected_contract_fields: set[str],
) -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Source report",
            "plan_rationale": "Summarize the source material in the confirmed shape.",
            "steps": [
                {
                    "name": "Summarize findings",
                    "instructions": (
                        "Summarize the confirmed findings and identify open questions."
                    ),
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            aggregation_intent="linear",
            report_disposition=report_disposition,
            result_contract_output_fields=(
                StructuredFieldDraft(
                    name="open_questions",
                    field_type="string",
                    description="Questions about {source} that remain unresolved.",
                ),
                StructuredFieldDraft(
                    name="key_points",
                    field_type="array",
                    description="Key points from the report.",
                    item_fields=[
                        StructuredFieldDraft(
                            name="point",
                            field_type="string",
                            description="One report point.",
                        )
                    ],
                ),
            ),
            runtime_max_files=4,
            ui_language="en",
        ),
    )

    assert compiled.steps[0].input_config is not None
    runtime_input = compiled.steps[0].input_config["runtime_input"]
    assert runtime_input["required"] is True
    assert runtime_input["max_files"] == 4
    assert runtime_input["execution_mode"] == "per_source"
    source_properties = compiled.steps[0].output_contract["properties"]["documents"][
        "items"
    ]["properties"]
    assert "source_material" in source_properties
    assert compiled.steps[-2].output_mode == OutputMode.COMPOSE_TEXT
    assert compiled.steps[-1].output_mode == OutputMode.RENDER_VERBATIM
    assert compiled.steps[-1].output_type == OutputType.PDF
    report_contract_fields = {
        "source_sections",
        "report_title",
        "overall_overview",
    }
    contract_fields = {
        field_name
        for step in compiled.steps
        for field_name in (step.output_contract or {}).get("properties", {})
        if field_name in report_contract_fields
    }
    assert contract_fields == expected_contract_fields
    assert any(
        "identify open questions" in step.assistant_spec.instructions
        for step in compiled.steps
    )
    assert any("open_questions" in str(step.output_contract) for step in compiled.steps)
    assert "open_questions" in str(compiled.steps[-2].input_bindings)
    assert "key_points" in str(compiled.steps[-2].input_bindings)
    assert all(
        step.input_source != InputSource.ALL_PREVIOUS_STEPS for step in compiled.steps
    )
    validation = validate_spec(compiled)
    assert validation.valid, validation.errors


def test_compiler_derives_whole_object_underlag() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Case summary",
            "flow_description": "Extract facts and write a short summary.",
            "plan_rationale": "Extract structured facts before writing.",
            "steps": [
                {
                    "name": "Extract facts",
                    "instructions": "Extract the relevant facts.",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Short summary.",
                        }
                    ],
                },
                {
                    "name": "Write summary",
                    "instructions": "Write the final summary.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_fields=(
                _confirmed_runtime_field("case_id", "Case ID", required=True),
            ),
        ),
    )

    assert len(compiled.steps) == 2
    extract_step = compiled.steps[0]
    assert extract_step.input_source == InputSource.FLOW_INPUT
    assert extract_step.input_type == InputType.TEXT
    assert extract_step.output_type == OutputType.JSON
    assert _question(extract_step.input_bindings) == (
        "{{ indata_text }}\n\ncase_id: {{ flow_input.case_id }}"
    )
    write_step = compiled.steps[1]
    assert write_step.input_source == InputSource.PREVIOUS_STEP
    assert write_step.input_type == InputType.TEXT
    assert write_step.output_type == OutputType.TEXT
    assert write_step.output_mode == OutputMode.PASS_THROUGH
    assert write_step.input_bindings == {
        "source_refs": [{"step_ref": "step_a", "output": "structured"}]
    }
    assert validate_spec(compiled).valid


def test_compiler_uses_assembly_path_for_whole_object_underlag() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Case report",
            "flow_description": "Extract facts and write a report.",
            "plan_rationale": "The writer needs the full extracted object.",
            "steps": [
                {
                    "name": "Extract facts",
                    "instructions": "Extract the relevant facts.",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Short summary.",
                        },
                        {
                            "name": "details",
                            "field_type": "string",
                            "description": "Important details.",
                        },
                    ],
                },
                {
                    "name": "Write report",
                    "instructions": "Write the final report.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(intent)

    assert len(compiled.steps) == 2
    write_step = compiled.steps[1]
    assert write_step.input_bindings == {
        "source_refs": [{"step_ref": "step_a", "output": "structured"}]
    }
    assert validate_spec(compiled).valid


def test_assembly_projects_one_structured_contract_to_each_section_writer() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Case report",
            "flow_description": "Extract facts and write three report sections.",
            "plan_rationale": "Each section needs the same structured facts.",
            "steps": [
                {
                    "name": "Extract facts",
                    "instructions": "Extract the reusable source facts.",
                    "output_fields": [
                        {
                            "name": "background",
                            "field_type": "string",
                            "description": "Relevant background.",
                        },
                        {
                            "name": "findings",
                            "field_type": "string",
                            "description": "Material findings.",
                        },
                        {
                            "name": "recommendations",
                            "field_type": "string",
                            "description": "Supported recommendations.",
                        },
                    ],
                },
                {
                    "name": "Write background",
                    "instructions": "Write the background section.",
                },
                {
                    "name": "Write findings",
                    "instructions": "Write the findings section.",
                },
                {
                    "name": "Write recommendations",
                    "instructions": "Write the recommendations section.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(intent)

    expected_source_refs = [
        {
            "step_ref": "step_a",
            "output": "structured",
            "field_path": field_name,
            "label": field_name,
        }
        for field_name in ("background", "findings", "recommendations")
    ]
    assert len(compiled.steps) == 4
    for writer in compiled.steps[1:]:
        assert writer.input_source == InputSource.PREVIOUS_STEP
        assert writer.input_bindings == {"source_refs": expected_source_refs}
    assert all(
        step.input_source != InputSource.ALL_PREVIOUS_STEPS for step in compiled.steps
    )
    assert validate_spec(compiled).valid


def test_assembly_rejects_ambiguous_structured_sources_before_lowering() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Ambiguous report",
            "flow_description": "Two structured stages precede section writers.",
            "plan_rationale": "The section source is not uniquely defined.",
            "steps": [
                {
                    "name": "Extract source facts",
                    "instructions": "Extract source facts.",
                    "output_fields": [
                        {
                            "name": "source_facts",
                            "field_type": "string",
                            "description": "Facts from the source.",
                        }
                    ],
                },
                {
                    "name": "Prepare report facts",
                    "instructions": "Prepare report facts.",
                    "output_fields": [
                        {
                            "name": "report_facts",
                            "field_type": "string",
                            "description": "Facts prepared for the report.",
                        }
                    ],
                },
                {
                    "name": "Write findings",
                    "instructions": "Write the findings section.",
                },
                {
                    "name": "Write recommendations",
                    "instructions": "Write the recommendations section.",
                },
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(intent)

    error = exc_info.value
    assert error.public_code == "architecture_materialization_failed"
    assert error.log_context["failure_code"] == (
        "section_writer_structured_source_ambiguous"
    )
    assert error.log_context["reason"] == ("section_writer_structured_source_ambiguous")
    assert error.log_context["step_index"] == 3
    assert "one structured preparation step" in error.detail
    assert "one supported terminal aggregate" in error.detail
    assert "uses_previous_fields" not in error.detail


def test_assembly_derives_terminal_writer_refs_for_multiple_json_priors() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Case report",
            "flow_description": "Extract, refine, and write a report.",
            "plan_rationale": "The final writer needs both structured stages.",
            "steps": [
                {
                    "name": "Extract facts",
                    "instructions": "Extract source facts.",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Short summary.",
                        }
                    ],
                },
                {
                    "name": "Find gaps",
                    "instructions": "Find missing information.",
                    "output_fields": [
                        {
                            "name": "missing_information",
                            "field_type": "string",
                            "description": "Missing information.",
                        }
                    ],
                },
                {
                    "name": "Write report",
                    "instructions": "Write the final report.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(intent)

    assert len(compiled.steps) == 3
    write_step = compiled.steps[2]
    assert write_step.input_bindings == {
        "source_refs": [
            {
                "step_ref": "step_a",
                "output": "structured",
                "field_path": "summary",
                "label": "summary",
            },
            {
                "step_ref": "step_b",
                "output": "structured",
                "field_path": "missing_information",
                "label": "missing information",
            },
        ]
    }
    assert validate_spec(compiled).valid


@pytest.mark.parametrize("final_output_type", [OutputType.PDF, OutputType.DOCX])
def test_compiler_uses_assembly_path_for_generated_document_renderer(
    final_output_type: OutputType,
) -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Document summary",
            "flow_description": "Write a short document from plain text input.",
            "plan_rationale": "One writer and one zero-token renderer.",
            "steps": [
                {
                    "name": "Write body",
                    "instructions": "Write the document body.",
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.TEXT,
            final_output_type=final_output_type,
            final_output_mode=OutputMode.RENDER_VERBATIM,
        ),
    )

    assert len(compiled.steps) == 2
    body_step = compiled.steps[0]
    renderer_step = compiled.steps[1]
    assert body_step.input_source == InputSource.FLOW_INPUT
    assert body_step.input_type == InputType.TEXT
    assert body_step.output_type == OutputType.TEXT
    assert body_step.output_mode == OutputMode.PASS_THROUGH
    assert renderer_step.input_source == InputSource.PREVIOUS_STEP
    assert renderer_step.input_type == InputType.TEXT
    assert renderer_step.output_type == final_output_type
    assert renderer_step.output_mode == OutputMode.RENDER_VERBATIM
    expected_render_copy = f"Rendera {final_output_type.value.upper()}"
    assert renderer_step.name == expected_render_copy
    assert renderer_step.assistant_spec.instructions == expected_render_copy
    assert renderer_step.input_bindings is None
    assert compiled.document_body_writer_step_refs == (body_step.plan_step_ref,)
    assert validate_spec(compiled).valid


def test_compiler_preserves_result_contract_fields_on_analysis_step() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Checklist review",
            "flow_description": "Compare an application against a checklist.",
            "plan_rationale": "Read the source, compare requirements, then write.",
            "steps": [
                {
                    "name": "Extract requirements",
                    "instructions": "Extract the application and checklist facts.",
                    "output_fields": [
                        {
                            "name": "requirements",
                            "field_type": "string",
                            "description": "Requirements from the source material.",
                        }
                    ],
                },
                {
                    "name": "Compare requirements",
                    "instructions": "Compare the application against the checklist.",
                    "output_fields": [
                        {
                            "name": "comparison_results",
                            "field_type": "array",
                            "description": "Per-requirement comparison results.",
                            "item_fields": [
                                {
                                    "name": "requirement",
                                    "field_type": "string",
                                    "description": "Requirement being checked.",
                                },
                                {
                                    "name": "status",
                                    "field_type": "string",
                                    "description": "Whether the requirement is met.",
                                },
                                {
                                    "name": "reason",
                                    "field_type": "string",
                                    "description": "Evidence for the status.",
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Write decision support",
                    "instructions": "Write the final checklist review.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.TEXT,
            result_contract_output_fields=(
                StructuredFieldDraft(
                    name="missing_information",
                    field_type="string",
                    description="Missing information.",
                ),
                StructuredFieldDraft(
                    name="uncertainty",
                    field_type="string",
                    description="Uncertain points.",
                ),
                StructuredFieldDraft(
                    name="recommended_action",
                    field_type="string",
                    description="Recommended next action.",
                ),
            ),
        ),
    )

    compare_contract = compiled.steps[1].output_contract
    assert compare_contract is not None
    assert set(compare_contract["properties"]) >= {
        "comparison_results",
        "missing_information",
        "uncertainty",
        "recommended_action",
    }
    assert compiled.steps[2].input_bindings == {
        "source_refs": [
            {
                "step_ref": "step_a",
                "output": "structured",
                "field_path": "requirements",
                "label": "requirements",
            },
            {
                "step_ref": "step_b",
                "output": "structured",
                "field_path": "comparison_results",
                "label": "comparison results",
            },
            {
                "step_ref": "step_b",
                "output": "structured",
                "field_path": "missing_information",
                "label": "missing information",
            },
            {
                "step_ref": "step_b",
                "output": "structured",
                "field_path": "uncertainty",
                "label": "uncertainty",
            },
            {
                "step_ref": "step_b",
                "output": "structured",
                "field_path": "recommended_action",
                "label": "recommended action",
            },
        ]
    }
    assert validate_spec(compiled).valid


def test_compiler_uses_typed_runtime_records_as_form_field_owner() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Bygglovsgranskning",
            "flow_description": "Jämför en ansökan mot angiven checklista.",
            "plan_rationale": "Läs ansökan, jämför mot regeln och skriv rapport.",
            "steps": [
                {
                    "name": "Läs ansökan",
                    "instructions": "Extrahera fakta ur ansökan.",
                    "output_fields": [
                        {
                            "name": "application_facts",
                            "field_type": "string",
                            "description": "Fakta ur ansökan.",
                        }
                    ],
                },
                {
                    "name": "Jämför krav",
                    "instructions": "Jämför ansökan mot checklistan eller regeln.",
                    "output_fields": [
                        {
                            "name": "requirements",
                            "field_type": "string",
                            "description": "Krav som ska bedömas.",
                        }
                    ],
                },
                {
                    "name": "Skriv rapport",
                    "instructions": "Skriv en tydlig rapport.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.TEXT,
            runtime_input_fields=(
                _confirmed_runtime_field(
                    "checklista", "checklista", purpose="whole_flow"
                ),
                _confirmed_runtime_field("regel", "regel", purpose="whole_flow"),
            ),
        ),
    )

    assert compiled.form_fields is not None
    assert [field.name for field in compiled.form_fields] == ["checklista", "regel"]
    assert [field.label for field in compiled.form_fields] == ["checklista", "regel"]
    assert [field.required for field in compiled.form_fields] == [False, False]
    comparison_step = next(
        step for step in compiled.steps if step.name == "Jämför krav"
    )
    assert comparison_step.input_type == InputType.TEXT
    assert comparison_step.input_contract is None
    comparison_question = _question(comparison_step.input_bindings)
    assert "checklista: {{ flow_input.checklista }}" in comparison_question
    assert "regel: {{ flow_input.regel }}" in comparison_question
    assert "flow_input.checklista" in repr(compiled.steps[-1].input_bindings)
    assert "flow_input.regel" in repr(compiled.steps[-1].input_bindings)
    assert validate_spec(compiled).valid


def test_compiler_uses_assembly_path_with_structural_pattern_hint() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "PDF briefing",
            "flow_description": "Create a generated PDF from text input.",
            "plan_rationale": "The pattern hint is architecture evidence only.",
            "steps": [
                {
                    "name": "Write briefing",
                    "instructions": "Write the briefing body.",
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.TEXT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            pattern_ids=("text_to_artifact_report",),
        ),
    )

    assert [step.output_type for step in compiled.steps] == [
        OutputType.TEXT,
        OutputType.PDF,
    ]
    assert compiled.steps[-1].output_mode == OutputMode.RENDER_VERBATIM
    assert validate_spec(compiled).valid


def test_compiler_uses_assembly_path_for_document_source_reader_chain() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Document findings",
            "flow_description": "Extract source facts and render a PDF.",
            "plan_rationale": "One source reader, one body writer, one renderer.",
            "steps": [
                {
                    "name": "Extract source facts",
                    "instructions": "Extract the source facts.",
                    "output_fields": [
                        {
                            "name": "finding",
                            "field_type": "string",
                            "description": "Important finding.",
                        }
                    ],
                },
                {
                    "name": "Write report body",
                    "instructions": "Write the report from the extracted facts.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            runtime_max_files=3,
        ),
    )

    assert len(compiled.steps) == 3
    reader_step = compiled.steps[0]
    body_step = compiled.steps[1]
    renderer_step = compiled.steps[2]
    assert reader_step.input_source == InputSource.FLOW_INPUT
    assert reader_step.input_type == InputType.DOCUMENT
    assert reader_step.output_type == OutputType.JSON
    assert reader_step.input_config is not None
    runtime_input = reader_step.input_config["runtime_input"]
    assert runtime_input["enabled"] is True
    assert runtime_input["required"] is True
    assert runtime_input["max_files"] == 3
    assert runtime_input["input_format"] == "document"
    assert body_step.input_source == InputSource.PREVIOUS_STEP
    assert body_step.input_type == InputType.TEXT
    assert body_step.output_type == OutputType.TEXT
    assert body_step.input_bindings == {
        "source_refs": [{"step_ref": "step_a", "output": "structured"}]
    }
    assert renderer_step.input_source == InputSource.PREVIOUS_STEP
    assert renderer_step.input_type == InputType.TEXT
    assert renderer_step.output_type == OutputType.PDF
    assert renderer_step.output_mode == OutputMode.RENDER_VERBATIM
    assert renderer_step.input_bindings is None
    assert compiled.document_body_writer_step_refs == (body_step.plan_step_ref,)
    assert validate_spec(compiled).valid


def test_assembly_rejects_confirmed_source_contract_shadow_form_field() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Document case summary",
            "plan_rationale": "The source reader owns the case id contract.",
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
        }
    )
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            intent,
            context=CreateCompileContext(
                runtime_input_type=InputType.DOCUMENT,
                runtime_input_fields=(_confirmed_runtime_field("case_id", "Case id"),),
            ),
        )

    assert exc_info.value.log_context["failure_code"] == (
        "confirmed_runtime_input_source_output_collision"
    )
    assert exc_info.value.log_context["field_names"] == "case_id"


def test_source_output_collision_is_exact_not_fuzzy() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Document case summary",
            "plan_rationale": "Keep runtime and source values distinct.",
            "steps": [
                {
                    "name": "Extract source facts",
                    "instructions": "Extract the source case id.",
                    "output_fields": [
                        {
                            "name": "source_case_id",
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
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            runtime_input_fields=(_confirmed_runtime_field("case_id", "Case id"),),
        ),
    )

    assert compiled.form_fields is not None
    assert [field.name for field in compiled.form_fields] == ["case_id"]
    assert compiled.steps[0].output_contract is not None
    assert "source_case_id" in compiled.steps[0].output_contract["properties"]


@pytest.mark.parametrize(
    ("final_output_type", "final_output_mode", "expected_output_types"),
    [
        (OutputType.TEXT, None, [OutputType.TEXT]),
        (
            OutputType.PDF,
            OutputMode.RENDER_VERBATIM,
            [OutputType.TEXT, OutputType.PDF],
        ),
        (
            OutputType.DOCX,
            OutputMode.RENDER_VERBATIM,
            [OutputType.TEXT, OutputType.DOCX],
        ),
    ],
)
def test_single_text_step_terminal_fields_do_not_conflict_with_runtime_inputs(
    final_output_type: OutputType,
    final_output_mode: OutputMode | None,
    expected_output_types: list[OutputType],
) -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Text case summary",
            "plan_rationale": "Write one prose result from the supplied text.",
            "steps": [
                {
                    "name": "Write summary",
                    "instructions": "Write the final summary.",
                    "output_fields": [
                        {
                            "name": "case_id",
                            "field_type": "string",
                            "description": "Display the supplied case id.",
                        }
                    ],
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.TEXT,
            final_output_type=final_output_type,
            final_output_mode=final_output_mode,
            runtime_input_fields=(_confirmed_runtime_field("case_id", "Case id"),),
        ),
    )

    assert compiled.form_fields is not None
    assert [field.name for field in compiled.form_fields] == ["case_id"]
    assert [step.output_type for step in compiled.steps] == expected_output_types
    assert compiled.steps[0].output_contract is None
    assert validate_spec(compiled).valid


def test_multi_step_text_source_output_collision_remains_repairable() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Text case analysis",
            "plan_rationale": "Extract the case id before writing the result.",
            "steps": [
                {
                    "name": "Extract source facts",
                    "instructions": "Extract the case id from the supplied text.",
                    "output_fields": [
                        {
                            "name": "case_id",
                            "field_type": "string",
                            "description": "Case id extracted from the source.",
                        }
                    ],
                },
                {
                    "name": "Write summary",
                    "instructions": "Write the final summary.",
                },
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            intent,
            context=CreateCompileContext(
                runtime_input_type=InputType.TEXT,
                final_output_type=OutputType.TEXT,
                runtime_input_fields=(_confirmed_runtime_field("case_id", "Case id"),),
            ),
        )

    assert exc_info.value.log_context["failure_code"] == (
        "confirmed_runtime_input_source_output_collision"
    )


def test_single_document_step_source_output_collision_remains_repairable() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Document case analysis",
            "plan_rationale": "Read the source before writing the result.",
            "steps": [
                {
                    "name": "Analyze document",
                    "instructions": "Extract the case id and write the result.",
                    "output_fields": [
                        {
                            "name": "case_id",
                            "field_type": "string",
                            "description": "Case id extracted from the document.",
                        }
                    ],
                }
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            intent,
            context=CreateCompileContext(
                runtime_input_type=InputType.DOCUMENT,
                final_output_type=OutputType.TEXT,
                runtime_input_fields=(_confirmed_runtime_field("case_id", "Case id"),),
            ),
        )

    assert exc_info.value.log_context["failure_code"] == (
        "confirmed_runtime_input_source_output_collision"
    )


def test_template_fill_source_output_collision_remains_repairable() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Template case report",
            "plan_rationale": "Prepare the case id for the document template.",
            "steps": [
                {
                    "name": "Prepare template content",
                    "instructions": "Prepare the template values.",
                    "output_fields": [
                        {
                            "name": "case_id",
                            "field_type": "string",
                            "description": "Case id prepared for the template.",
                        }
                    ],
                }
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            intent,
            context=CreateCompileContext(
                runtime_input_type=InputType.DOCUMENT,
                final_output_type=OutputType.DOCX,
                final_output_mode=OutputMode.TEMPLATE_FILL,
                pattern_ids=("document_to_docx_template",),
                pattern_chain_steps=(
                    FLOW_INPUT_DOCUMENT_UPLOAD,
                    EXTRACT_TEMPLATE_VARIABLES_STEP,
                    PREPARE_TEMPLATE_CONTENT_STEP,
                    TEMPLATE_FILL_DOCX_STEP,
                ),
                runtime_input_fields=(_confirmed_runtime_field("case_id", "Case id"),),
            ),
        )

    assert exc_info.value.log_context["failure_code"] == (
        "confirmed_runtime_input_source_output_collision"
    )


@pytest.mark.parametrize(
    ("runtime_name", "output_name", "purpose"),
    [
        ("case_id", "CASE-ID", "interpret_input"),
        ("arende_id", "Ärende id", "shape_result"),
        ("policy_level", "policy.level", "whole_flow"),
        ("source_file_id", "source-file-id", "interpret_input"),
    ],
)
def test_provider_source_output_collision_uses_folded_identity_for_all_purposes(
    runtime_name: str,
    output_name: str,
    purpose: RuntimeMetadataFieldPurpose,
) -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Document analysis",
            "plan_rationale": "Extract source facts.",
            "steps": [
                {
                    "name": "Extract source facts",
                    "instructions": "Extract the named field.",
                    "output_fields": [
                        {
                            "name": output_name,
                            "field_type": "string",
                            "description": "Value found in the source.",
                        }
                    ],
                },
                {
                    "name": "Write summary",
                    "instructions": "Write the final summary.",
                },
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            intent,
            context=CreateCompileContext(
                runtime_input_type=InputType.DOCUMENT,
                runtime_input_fields=(
                    _confirmed_runtime_field(
                        runtime_name,
                        runtime_name,
                        purpose=purpose,
                    ),
                ),
            ),
        )

    assert exc_info.value.log_context["failure_code"] == (
        "confirmed_runtime_input_source_output_collision"
    )
    assert exc_info.value.log_context["field_names"] == runtime_name


@pytest.mark.parametrize("runtime_name", ["source_label", "source_file_id"])
def test_provider_authored_runtime_identity_collision_remains_repairable(
    runtime_name: str,
) -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Document source identities",
            "plan_rationale": "Extract a source record.",
            "steps": [
                {
                    "name": "Read documents",
                    "instructions": "Extract source-grounded facts.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "One record per source.",
                            "item_fields": [
                                {
                                    "name": runtime_name,
                                    "field_type": "string",
                                    "description": "Provider-authored source identity.",
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "Write summary",
                    "instructions": "Write the final summary.",
                },
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            intent,
            context=CreateCompileContext(
                runtime_input_type=InputType.DOCUMENT,
                runtime_input_fields=(
                    _confirmed_runtime_field(runtime_name, runtime_name),
                ),
            ),
        )

    assert exc_info.value.log_context["failure_code"] == (
        "confirmed_runtime_input_source_output_collision"
    )
    assert exc_info.value.log_context["field_names"] == runtime_name


def test_injected_source_output_collision_keeps_confirmed_runtime_field() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Document case summary",
            "plan_rationale": "Add the server-owned source contract.",
            "steps": [
                {
                    "name": "Write summary",
                    "instructions": "Write the final summary.",
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            runtime_input_fields=(_confirmed_runtime_field("case_id", "Case id"),),
            source_reader_required_fields=(
                SourceCaptureField(
                    name="case_id",
                    description="Case id extracted from the source.",
                ),
            ),
        ),
    )

    assert compiled.form_fields is not None
    assert [field.name for field in compiled.form_fields] == ["case_id"]
    assert compiled.steps[0].output_contract is not None
    assert "source_case_id" in compiled.steps[0].output_contract["properties"]


@pytest.mark.parametrize(
    ("runtime_name", "expected_source_name"),
    [
        ("source_material", "source_source_material"),
    ],
)
def test_document_report_injected_field_collision_keeps_confirmed_runtime_field(
    runtime_name: str,
    expected_source_name: str,
) -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Document report",
            "plan_rationale": "Build the server-owned document report shape.",
            "steps": [
                {
                    "name": "Write report",
                    "instructions": "Write the final report.",
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            report_disposition="synthesized_overview",
            runtime_input_fields=(
                _confirmed_runtime_field(runtime_name, runtime_name),
            ),
        ),
    )

    assert compiled.form_fields is not None
    assert [field.name for field in compiled.form_fields] == [runtime_name]
    assert compiled.steps[0].output_contract is not None
    source_properties = compiled.steps[0].output_contract["properties"]["documents"][
        "items"
    ]["properties"]
    assert expected_source_name in source_properties
    assert validate_spec(compiled).valid


@pytest.mark.parametrize("runtime_name", ["source_label", "source_file_id"])
def test_runtime_identity_injection_does_not_conflict_with_confirmed_field(
    runtime_name: str,
) -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Multi-source report",
            "plan_rationale": "Build one source record per document.",
            "steps": [
                {
                    "name": "Read documents",
                    "instructions": "Extract source-grounded facts.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "One record per source.",
                            "item_fields": [
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
                    "name": "Write report",
                    "instructions": "Write the final report.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            runtime_max_files=4,
            runtime_input_fields=(
                _confirmed_runtime_field(runtime_name, "External source identity"),
            ),
        ),
    )

    assert compiled.form_fields is not None
    assert [field.name for field in compiled.form_fields] == [runtime_name]
    reader_properties = compiled.steps[0].output_contract["properties"]["documents"][
        "items"
    ]["properties"]
    assert runtime_name in reader_properties
    assert validate_spec(compiled).valid


def test_confirmed_field_definition_is_the_compiled_value_owner() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Case routing",
            "plan_rationale": "Route the case using its confirmed type.",
            "steps": [
                {
                    "name": "Route case",
                    "instructions": "Route the case using its type.",
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_fields=(
                ConfirmedRuntimeMetadataField(
                    value=FlowInputFieldIntent(
                        variable_name="case_type",
                        label="Confirmed case type",
                        field_type="select",
                        required=True,
                        options=["permit", "complaint"],
                        provenance="user_confirmed",
                    ),
                    purpose="interpret_input",
                    structured_answer_message_id="message-1",
                ),
            ),
        ),
    )

    assert compiled.form_fields is not None
    assert compiled.form_fields[0].model_dump(exclude_none=True) == {
        "name": "case_type",
        "label": "Confirmed case type",
        "type": "select",
        "required": True,
        "options": ["permit", "complaint"],
    }


@pytest.mark.parametrize("aggregation_intent", ["aggregate", "compare"])
def test_compiler_uses_source_refs_for_structured_terminal_fan_in(
    aggregation_intent: AggregationIntent,
) -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Aggregate report",
            "flow_description": "Extract, analyze, and render a PDF report.",
            "plan_rationale": "The body writer aggregates compact prior work.",
            "steps": [
                {
                    "name": "Extract source facts",
                    "instructions": "Extract the source facts.",
                    "output_fields": [
                        {
                            "name": "source_summary",
                            "field_type": "string",
                            "description": "Source summary.",
                        }
                    ],
                },
                {
                    "name": "Analyze facts",
                    "instructions": "Analyze the extracted facts.",
                    "output_fields": [
                        {
                            "name": "analysis",
                            "field_type": "string",
                            "description": "Analysis summary.",
                        }
                    ],
                },
                {
                    "name": "Write report body",
                    "instructions": "Write the final report body from prior work.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            aggregation_intent=aggregation_intent,
        ),
    )

    body_step = compiled.steps[-2]
    renderer_step = compiled.steps[-1]
    assert [step.output_type for step in compiled.steps] == [
        OutputType.JSON,
        OutputType.JSON,
        OutputType.TEXT,
        OutputType.PDF,
    ]
    assert body_step.input_source == InputSource.PREVIOUS_STEP
    assert body_step.input_type == InputType.TEXT
    assert body_step.input_bindings == {
        "source_refs": [
            {
                "step_ref": "step_a",
                "output": "structured",
                "field_path": "source_summary",
                "label": "source summary",
            },
            {
                "step_ref": "step_b",
                "output": "structured",
                "field_path": "analysis",
                "label": "analysis",
            },
        ]
    }
    assert renderer_step.input_source == InputSource.PREVIOUS_STEP
    assert renderer_step.input_type == InputType.TEXT
    assert renderer_step.output_mode == OutputMode.RENDER_VERBATIM
    assert renderer_step.input_bindings is None
    assert compiled.document_body_writer_step_refs == (body_step.plan_step_ref,)
    assert validate_spec(compiled).valid


def test_aggregate_document_body_uses_previous_step_for_single_prior_reader() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Document report",
            "flow_description": "Extract facts and render a PDF report.",
            "plan_rationale": "The body writer consumes the single reader output.",
            "steps": [
                {
                    "name": "Extract source facts",
                    "instructions": "Extract the source facts.",
                    "output_fields": [
                        {
                            "name": "facts",
                            "field_type": "array",
                            "description": "Source facts.",
                        }
                    ],
                },
                {
                    "name": "Write report body",
                    "instructions": "Write the final report body from the facts.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            aggregation_intent=cast(AggregationIntent, "aggregate"),
        ),
    )

    body_step = compiled.steps[-2]
    assert [step.output_type for step in compiled.steps] == [
        OutputType.JSON,
        OutputType.TEXT,
        OutputType.PDF,
    ]
    assert body_step.input_source == InputSource.PREVIOUS_STEP
    assert body_step.input_bindings == {
        "source_refs": [{"step_ref": "step_a", "output": "structured"}]
    }
    assert validate_spec(compiled).valid


def test_assembly_source_reader_contract_keeps_all_terminal_schema_leaves() -> None:
    required_properties = {f"field_{index}": {"type": "string"} for index in range(10)}
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Document JSON",
            "flow_description": "Extract source facts and emit the requested JSON.",
            "plan_rationale": "One source reader and one JSON terminal step.",
            "steps": [
                {
                    "name": "Extract source facts",
                    "instructions": "Extract the source facts.",
                    "output_fields": [
                        {
                            "name": "field_0",
                            "field_type": "string",
                            "description": "First field.",
                        }
                    ],
                },
                {
                    "name": "Build JSON result",
                    "instructions": "Build the requested JSON result.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.JSON,
            terminal_output_schema={
                "type": "object",
                "properties": required_properties,
            },
        ),
    )

    source_contract = compiled.steps[0].output_contract
    terminal_contract = compiled.steps[-1].output_contract
    assert source_contract is not None
    assert sorted(source_contract["properties"]) == [
        f"field_{index}" for index in range(10)
    ]
    assert terminal_contract == {
        "type": "object",
        "properties": required_properties,
    }
    assert validate_spec(compiled).valid


@pytest.mark.parametrize(
    ("context", "expected"),
    [
        (
            CreateCompileContext(
                runtime_input_type=InputType.AUDIO,
                final_output_type=OutputType.TEXT,
                final_output_mode=OutputMode.TRANSCRIBE_ONLY,
                post_processing_goal="stop_after_primary_operation",
            ),
            True,
        ),
        (
            CreateCompileContext(
                runtime_input_type=InputType.AUDIO,
                final_output_type=OutputType.TEXT,
                final_output_mode=OutputMode.TRANSCRIBE_ONLY,
                pattern_ids=("audio_transcription",),
                post_processing_goal="summarize_or_overview",
            ),
            False,
        ),
        (
            CreateCompileContext(
                runtime_input_type=InputType.AUDIO,
                final_output_type=OutputType.TEXT,
                final_output_mode=OutputMode.TRANSCRIBE_ONLY,
                post_processing_goal="stop_after_primary_operation",
                secondary_obligations=("summary",),
            ),
            False,
        ),
        (
            CreateCompileContext(
                runtime_input_type=InputType.TEXT,
                final_output_type=OutputType.TEXT,
                final_output_mode=OutputMode.TRANSCRIBE_ONLY,
                pattern_ids=("audio_transcription",),
                post_processing_goal="stop_after_primary_operation",
            ),
            False,
        ),
        (
            CreateCompileContext(
                runtime_input_type=InputType.AUDIO,
                final_output_type=OutputType.TEXT,
                pattern_ids=("audio_transcription",),
                post_processing_goal="stop_after_primary_operation",
            ),
            False,
        ),
    ],
)
def test_create_compile_context_owns_pure_audio_transcription_classification(
    context: CreateCompileContext,
    expected: bool,
) -> None:
    assert context.is_pure_audio_transcription is expected


def test_compiler_uses_assembly_path_for_pure_audio_transcription() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Meeting transcript",
            "flow_description": "Transcribe uploaded meeting audio.",
            "plan_rationale": "The runtime transcription step is the output.",
            "steps": [
                {
                    "name": "Transcribe meeting audio",
                    "instructions": "Transcribe the uploaded meeting audio.",
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.AUDIO,
            final_output_type=OutputType.TEXT,
            final_output_mode=OutputMode.TRANSCRIBE_ONLY,
            pattern_ids=("audio_transcription",),
            post_processing_goal="stop_after_primary_operation",
            runtime_max_files=1,
        ),
    )

    assert len(compiled.steps) == 1
    step = compiled.steps[0]
    assert step.input_source == InputSource.FLOW_INPUT
    assert step.input_type == InputType.AUDIO
    assert step.output_type == OutputType.TEXT
    assert step.output_mode == OutputMode.TRANSCRIBE_ONLY
    assert step.input_config is not None
    runtime_input = step.input_config["runtime_input"]
    assert runtime_input["enabled"] is True
    assert runtime_input["required"] is True
    assert runtime_input["max_files"] == 1
    assert runtime_input["input_format"] == "audio"
    assert validate_spec(compiled).valid


def test_compiler_rejects_structured_shape_for_pure_audio_transcription() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Meeting transcript",
            "flow_description": "Transcribe uploaded meeting audio.",
            "plan_rationale": "The runtime transcription step is the output.",
            "steps": [
                {
                    "name": "Transcribe meeting audio",
                    "instructions": "Transcribe the uploaded meeting audio.",
                    "output_fields": [
                        {
                            "name": "transcript",
                            "field_type": "string",
                            "description": "The transcript text.",
                            "required": True,
                        }
                    ],
                }
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            intent,
            context=CreateCompileContext(
                runtime_input_type=InputType.AUDIO,
                final_output_type=OutputType.TEXT,
                final_output_mode=OutputMode.TRANSCRIBE_ONLY,
                post_processing_goal="stop_after_primary_operation",
            ),
        )

    assert exc_info.value.log_context["failure_code"] == (
        "assembly_pure_audio_transcription_shape_unsupported"
    )


@pytest.mark.parametrize(
    ("post_processing_goal", "secondary_obligations"),
    [
        ("summarize_or_overview", ()),
        ("action_followup", ()),
        ("stop_after_primary_operation", ("summary",)),
    ],
)
def test_compiler_never_downgrades_audio_post_processing_to_transcript_only(
    post_processing_goal: str,
    secondary_obligations: tuple[ResultObligation, ...],
) -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Meeting result",
            "plan_rationale": "Produce the requested result from meeting audio.",
            "steps": [
                {
                    "name": "Process meeting audio",
                    "instructions": "Produce the requested source-grounded result.",
                }
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            intent,
            context=CreateCompileContext(
                runtime_input_type=InputType.AUDIO,
                final_output_type=OutputType.TEXT,
                final_output_mode=OutputMode.TRANSCRIBE_ONLY,
                post_processing_goal=post_processing_goal,
                secondary_obligations=secondary_obligations,
            ),
        )

    assert exc_info.value.log_context["failure_code"] == (
        "assembly_unsupported_output_mode"
    )


def test_compiler_projects_typed_checkpoint_intents_onto_actual_producers() -> None:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "audio"),
        "terminal_output": _slot("terminal_output", "docx_document"),
    }
    state.checkpoint_intents = [
        CheckpointIntent(
            producer_kind="transcript",
            operation="set",
            mode=FlowStepReviewMode.EDIT,
            confidence="high",
            evidence=["quote:user_message:1:Edit the transcript."],
        ),
        CheckpointIntent(
            producer_kind="structured_result",
            operation="set",
            mode=FlowStepReviewMode.VIEW,
            confidence="high",
            evidence=["quote:user_message:1:Approve the extracted facts."],
        ),
        CheckpointIntent(
            producer_kind="report_text",
            operation="set",
            mode=FlowStepReviewMode.EDIT,
            confidence="high",
            evidence=["quote:user_message:1:Edit the report before rendering."],
        ),
    ]
    _commit_architecture(state)

    context = create_compile_context_from_planning_state(state, ui_language="en")

    assert context is not None
    assert context.checkpoint_intents == tuple(state.checkpoint_intents)
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Reviewed meeting report",
            "plan_rationale": "Extract facts and write the reviewed report.",
            "steps": [
                {
                    "name": "Extract meeting facts",
                    "instructions": "Extract the decisions and owners from the transcript.",
                    "output_fields": [
                        {
                            "name": "decisions",
                            "field_type": "array",
                            "description": "Decisions made during the meeting.",
                        }
                    ],
                },
                {
                    "name": "Write meeting report",
                    "instructions": "Write the final report from the extracted facts.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(intent, context=context)

    transcription, structured_result, report_text, renderer = compiled.steps
    assert transcription.output_mode is OutputMode.TRANSCRIBE_ONLY
    assert transcription.review_policy is not None
    assert transcription.review_policy.mode is FlowStepReviewMode.EDIT
    assert structured_result.output_type is OutputType.JSON
    assert structured_result.review_policy is not None
    assert structured_result.review_policy.mode is FlowStepReviewMode.VIEW
    assert report_text.plan_step_ref in (compiled.document_body_writer_step_refs or ())
    assert report_text.review_policy is not None
    assert report_text.review_policy.mode is FlowStepReviewMode.EDIT
    assert renderer.output_mode is OutputMode.RENDER_VERBATIM
    assert renderer.review_policy is None


def test_structured_checkpoint_lands_on_terminal_json_producer_only() -> None:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "audio"),
        "terminal_output": _slot("terminal_output", "docx_document"),
    }
    state.checkpoint_intents = [
        CheckpointIntent(
            producer_kind="structured_result",
            operation="set",
            mode=FlowStepReviewMode.VIEW,
            confidence="high",
            evidence=["quote:user_message:1:Approve the final extracted data."],
        )
    ]
    _commit_architecture(state)
    context = create_compile_context_from_planning_state(state, ui_language="en")
    assert context is not None
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Two-stage extraction report",
            "plan_rationale": "Extract, refine, then write the report.",
            "steps": [
                {
                    "name": "Extract raw facts",
                    "instructions": "Extract raw decisions from the transcript.",
                    "output_fields": [
                        {
                            "name": "raw_decisions",
                            "field_type": "array",
                            "description": "Raw decision candidates.",
                        }
                    ],
                },
                {
                    "name": "Refine decisions",
                    "instructions": "Deduplicate and refine the decisions.",
                    "output_fields": [
                        {
                            "name": "decisions",
                            "field_type": "array",
                            "description": "Final decisions.",
                        }
                    ],
                },
                {
                    "name": "Write report",
                    "instructions": "Write the report from the final decisions.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(intent, context=context)

    json_steps = [
        step for step in compiled.steps if step.output_type is OutputType.JSON
    ]
    assert len(json_steps) == 2
    first_json, terminal_json = json_steps
    assert first_json.review_policy is None
    assert terminal_json.review_policy is not None
    assert terminal_json.review_policy.mode is FlowStepReviewMode.VIEW
    reviewed_refs = [
        step.plan_step_ref for step in compiled.steps if step.review_policy is not None
    ]
    assert reviewed_refs == [terminal_json.plan_step_ref]


def test_transcript_checkpoint_without_transcription_step_is_a_contradiction() -> None:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "text"),
        "terminal_output": _slot("terminal_output", "structured_text"),
    }
    state.checkpoint_intents = [
        CheckpointIntent(
            producer_kind="transcript",
            operation="set",
            mode=FlowStepReviewMode.EDIT,
            confidence="high",
            evidence=["quote:user_message:1:Edit the transcript."],
        )
    ]
    _commit_architecture(state)
    context = create_compile_context_from_planning_state(state, ui_language="en")
    assert context is not None
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Text summary",
            "plan_rationale": "Summarize the text.",
            "steps": [
                {
                    "name": "Summarize",
                    "instructions": "Summarize the submitted text.",
                }
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(intent, context=context)

    assert (
        exc_info.value.log_context["failure_code"]
        == "checkpoint_transcript_producer_missing"
    )


@pytest.mark.parametrize(
    ("ui_language", "actual_input_prefix"),
    [
        (
            "sv",
            "Faktiskt underlag: Det här steget får den fullständiga "
            "texttranskriberingen",
        ),
        (
            "en",
            "Actual input: This step receives the complete text transcript",
        ),
    ],
)
def test_compiler_describes_transcript_input_and_avoids_raw_audio_report_fan_in(
    ui_language: str,
    actual_input_prefix: str,
) -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Meeting report",
            "flow_description": "Create a DOCX report from meeting audio.",
            "plan_rationale": "Transcribe, structure, write, and render.",
            "steps": [
                {
                    "name": "Extract transcript facts",
                    "instructions": "Extract the key facts from the transcript.",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Short meeting summary.",
                        }
                    ],
                },
                {
                    "name": "Write report body",
                    "instructions": "Write the final report body.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.AUDIO,
            final_output_type=OutputType.DOCX,
            final_output_mode=OutputMode.PASS_THROUGH,
            pattern_ids=("audio_to_artifact_report",),
            pattern_chain_steps=(
                FLOW_INPUT_AUDIO_TRANSCRIPTION,
                TERMINAL_ARTIFACT_STEP,
            ),
            runtime_max_files=1,
            ui_language=ui_language,
        ),
    )

    assert [step.input_type for step in compiled.steps] == [
        InputType.AUDIO,
        InputType.TEXT,
        InputType.TEXT,
        InputType.TEXT,
    ]
    assert [step.output_type for step in compiled.steps] == [
        OutputType.TEXT,
        OutputType.JSON,
        OutputType.TEXT,
        OutputType.DOCX,
    ]
    transcription_step = compiled.steps[0]
    extract_step = compiled.steps[1]
    body_step = compiled.steps[2]
    renderer_step = compiled.steps[3]
    assert transcription_step.output_mode == OutputMode.TRANSCRIBE_ONLY
    assert transcription_step.input_config is not None
    assert transcription_step.input_config["runtime_input"]["input_format"] == "audio"
    assert extract_step.input_source == InputSource.PREVIOUS_STEP
    assert extract_step.assistant_spec.instructions.startswith(actual_input_prefix)
    assert body_step.input_bindings == {
        "source_refs": [{"step_ref": "step_b", "output": "structured"}]
    }
    assert _question(body_step.input_bindings) == "{{ step_b.output.structured }}"
    assert body_step.input_contract is None
    assert renderer_step.output_mode == OutputMode.RENDER_VERBATIM
    assert renderer_step.input_bindings is None
    assert compiled.document_body_writer_step_refs == (body_step.plan_step_ref,)
    assert validate_spec(compiled).valid


def test_compiler_accepts_audio_artifact_with_runtime_form_field_overlay() -> None:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "audio"),
        "terminal_output": _slot("terminal_output", "docx_document"),
        "runtime_metadata_fields": _slot(
            "runtime_metadata_fields",
            "detailed_runtime_metadata",
        ),
    }
    state.input_fields = [
        _confirmed_runtime_field("arendenummer", "ärendenummer", purpose="whole_flow"),
        _confirmed_runtime_field("handlaggare", "handläggare", purpose="whole_flow"),
    ]
    state.checkpoint_intents = [
        CheckpointIntent(
            producer_kind="structured_result",
            operation="set",
            mode=FlowStepReviewMode.EDIT,
            confidence="high",
            evidence=["quote:user_message:1:Edit the extracted facts."],
        )
    ]
    architecture = derive_architecture_commit_draft(state)

    assert architecture is not None
    assert architecture.chosen_patterns == [
        "audio_to_artifact_report",
        "form_field_runtime_inputs",
    ]
    _commit_architecture(state)

    context = create_compile_context_from_planning_state(
        state,
        ui_language="sv",
    )
    assert context is not None
    assert context.pattern_ids == tuple(architecture.chosen_patterns)
    assert context.pattern_chain_steps == (
        FLOW_INPUT_AUDIO_TRANSCRIPTION,
        TERMINAL_ARTIFACT_STEP,
    )

    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Ljudbaserad ärenderapport",
            "flow_description": "Analysera ett ljudunderlag och skapa en DOCX.",
            "plan_rationale": "Transkribera, analysera, skriv och rendera.",
            "steps": [
                {
                    "name": "Analysera transkriptionen",
                    "instructions": "Identifiera de viktigaste sakuppgifterna.",
                    "output_fields": [
                        {
                            "name": "sakuppgifter",
                            "field_type": "string",
                            "description": "Verifierade sakuppgifter ur ljudet.",
                        }
                    ],
                },
                {
                    "name": "Skriv rapporten",
                    "instructions": "Skriv en tydlig rapport från sakuppgifterna.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(intent, context=context)

    assert [field.name for field in compiled.form_fields or ()] == [
        "arendenummer",
        "handlaggare",
    ]
    assert [step.name for step in compiled.steps[1:3]] == [
        "Analysera transkriptionen",
        "Skriv rapporten",
    ]
    transcription_step, analysis_step, report_step, renderer_step = compiled.steps
    assert transcription_step.output_mode == OutputMode.TRANSCRIBE_ONLY
    assert transcription_step.input_type == InputType.AUDIO
    assert analysis_step.output_type == OutputType.JSON
    assert analysis_step.input_type == InputType.TEXT
    assert analysis_step.input_bindings == {
        "question": (
            "arendenummer: {{ flow_input.arendenummer }}\n"
            "handlaggare: {{ flow_input.handlaggare }}"
        ),
        "source_refs": [{"step_ref": "step_a", "output": "text"}],
    }
    assert analysis_step.assistant_spec.instructions.startswith(
        "Faktiskt underlag: Det här steget får den fullständiga texttranskriberingen"
    )
    assert analysis_step.review_policy is not None
    assert analysis_step.review_policy.mode.value == "edit"
    assert report_step.review_policy is None
    report_question = _question(report_step.input_bindings)
    assert "arendenummer: {{ flow_input.arendenummer }}" in report_question
    assert "handlaggare: {{ flow_input.handlaggare }}" in report_question
    for step in (transcription_step, renderer_step):
        assert "flow_input.arendenummer" not in repr(step.input_bindings)
        assert "flow_input.handlaggare" not in repr(step.input_bindings)
    assert renderer_step.output_mode == OutputMode.RENDER_VERBATIM
    assert renderer_step.output_type == OutputType.DOCX
    assert validate_spec(compiled).valid


@pytest.mark.parametrize(
    "conflicting_pattern_id",
    ["text_to_artifact_report", "unknown_compiled_pattern"],
)
def test_audio_artifact_overlay_still_rejects_conflicting_patterns(
    conflicting_pattern_id: str,
) -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Ljudrapport",
            "plan_rationale": "Transkribera och skriv en rapport.",
            "steps": [
                {
                    "name": "Skriv rapporten",
                    "instructions": "Skriv rapporten från transkriptionen.",
                }
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            intent,
            context=CreateCompileContext(
                runtime_input_type=InputType.AUDIO,
                final_output_type=OutputType.DOCX,
                final_output_mode=OutputMode.PASS_THROUGH,
                pattern_ids=(
                    "audio_to_artifact_report",
                    "form_field_runtime_inputs",
                    conflicting_pattern_id,
                ),
                pattern_chain_steps=(
                    FLOW_INPUT_AUDIO_TRANSCRIPTION,
                    TERMINAL_ARTIFACT_STEP,
                ),
            ),
        )

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.log_context["failure_code"] == (
        "assembly_unsupported_architecture_hints"
    )


@pytest.mark.parametrize("aggregation_intent", ["linear", "aggregate", "compare"])
def test_compiler_binds_human_named_placeholders_from_prepared_terminal(
    aggregation_intent: str,
) -> None:
    """The flagship shape: a JSON terminal prepares folded placeholder fields.

    Human-named placeholders bind to the prepared fields; metadata
    placeholders the flow does not prepare stay runtime form fields and
    need no semantic-step reference because the template consumes them.
    Cross-checking several sources (aggregate/compare) is preparation
    work inside the same fixed template topology.
    """

    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Tjänsteskrivelse från underlag",
            "flow_description": "Fill the municipal template from sources.",
            "plan_rationale": "Extract, structure, and fill the template.",
            "steps": [
                {
                    "name": "Extrahera underlag",
                    "instructions": "Extract source-grounded facts.",
                    "output_fields": [
                        {
                            "name": "sources",
                            "field_type": "string",
                            "description": "Source-grounded findings.",
                        }
                    ],
                },
                {
                    "name": "Förbered malltexter",
                    "instructions": "Write the final template section texts.",
                    "output_fields": [
                        {
                            "name": "sections_arendet_text",
                            "field_type": "string",
                            "description": "Final text for the Ärendet section.",
                        },
                        {
                            "name": "sections_bakgrund_text",
                            "field_type": "string",
                            "description": "Final text for the Bakgrund section.",
                        },
                    ],
                },
            ],
        }
    )

    context = CreateCompileContext(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.DOCX,
        final_output_mode=OutputMode.TEMPLATE_FILL,
        pattern_ids=("document_to_docx_template",),
        pattern_chain_steps=(
            FLOW_INPUT_DOCUMENT_UPLOAD,
            EXTRACT_TEMPLATE_VARIABLES_STEP,
            PREPARE_TEMPLATE_CONTENT_STEP,
            TEMPLATE_FILL_DOCX_STEP,
        ),
        runtime_max_files=6,
        aggregation_intent=cast(AggregationIntent, aggregation_intent),
        selected_template_count=1,
        selected_template_placeholders=(
            "diarienummer",
            "sections.ärendet.text",
            "sections.bakgrund.text",
        ),
        template_placeholder_field_hints=(
            RuntimeInputFieldHint(
                variable_name="diarienummer",
                label="diarienummer",
                required=True,
                provenance="template_derived",
            ),
        ),
    )
    compiled = compile_create_intent_to_spec(intent, context=context)

    assert len(compiled.steps) == 4
    prepare_step = compiled.steps[2]
    template_step = compiled.steps[3]
    assert prepare_step.output_type == OutputType.JSON
    assert template_step.output_mode == OutputMode.TEMPLATE_FILL
    assert template_step.output_config == {
        "bindings": {
            "diarienummer": "{{ flow_input.diarienummer }}",
            "sections.ärendet.text": (
                "{{ "
                + str(prepare_step.plan_step_ref)
                + ".output.structured.sections_arendet_text }}"
            ),
            "sections.bakgrund.text": (
                "{{ "
                + str(prepare_step.plan_step_ref)
                + ".output.structured.sections_bakgrund_text }}"
            ),
        }
    }
    # The metadata placeholder stays a required runtime form field even
    # though no semantic step references it: the template is its consumer.
    assert [field.name for field in compiled.form_fields or ()] == ["diarienummer"]


def test_compiler_drops_template_form_field_when_flow_prepares_it() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Tjänsteskrivelse från underlag",
            "flow_description": "Fill the municipal template from sources.",
            "plan_rationale": "Extract the metadata and fill the template.",
            "steps": [
                {
                    "name": "Förbered malltexter",
                    "instructions": "Extract metadata and section texts.",
                    "output_fields": [
                        {
                            "name": "diarienummer",
                            "field_type": "string",
                            "description": "The case number from the sources.",
                        }
                    ],
                },
            ],
        }
    )

    context = CreateCompileContext(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.DOCX,
        final_output_mode=OutputMode.TEMPLATE_FILL,
        pattern_ids=("document_to_docx_template",),
        pattern_chain_steps=(
            FLOW_INPUT_DOCUMENT_UPLOAD,
            EXTRACT_TEMPLATE_VARIABLES_STEP,
            PREPARE_TEMPLATE_CONTENT_STEP,
            TEMPLATE_FILL_DOCX_STEP,
        ),
        selected_template_count=1,
        selected_template_placeholders=("diarienummer",),
        template_placeholder_field_hints=(
            RuntimeInputFieldHint(
                variable_name="diarienummer",
                label="diarienummer",
                required=True,
                provenance="template_derived",
            ),
        ),
    )
    compiled = compile_create_intent_to_spec(intent, context=context)

    prepare_step = compiled.steps[1]
    assert compiled.steps[-1].output_config == {
        "bindings": {
            "diarienummer": (
                "{{ "
                + str(prepare_step.plan_step_ref)
                + ".output.structured.diarienummer }}"
            ),
        }
    }
    assert not compiled.form_fields


def test_compiler_admits_three_semantic_steps_before_fixed_template_fill() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Template report",
            "flow_description": "Fill a DOCX template from source documents.",
            "plan_rationale": "Analyze, validate, write, and fill the template.",
            "steps": [
                {
                    "name": "Analyze source facts",
                    "instructions": "Analyze the source facts for the report.",
                    "output_fields": [
                        {
                            "name": "case_summary",
                            "field_type": "string",
                            "description": "A source-grounded case summary.",
                        }
                    ],
                },
                {
                    "name": "Validate source facts",
                    "instructions": "Validate the analyzed facts for consistency.",
                    "output_fields": [
                        {
                            "name": "validated_summary",
                            "field_type": "string",
                            "description": "The validated case summary.",
                        }
                    ],
                },
                {
                    "name": "Write template content",
                    "instructions": "Write the prepared result as template content.",
                },
            ],
        }
    )

    context = CreateCompileContext(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.DOCX,
        final_output_mode=OutputMode.TEMPLATE_FILL,
        pattern_ids=("document_to_docx_template",),
        pattern_chain_steps=(
            FLOW_INPUT_DOCUMENT_UPLOAD,
            EXTRACT_TEMPLATE_VARIABLES_STEP,
            PREPARE_TEMPLATE_CONTENT_STEP,
            TEMPLATE_FILL_DOCX_STEP,
        ),
        runtime_max_files=2,
        selected_template_count=1,
        selected_template_placeholders=(
            "step_a.output.structured.source_facts",
            "step_b.output.structured.case_summary",
            "step_c.output.structured.validated_summary",
            "föregående_steg",
        ),
    )
    compiled = compile_create_intent_to_spec(intent, context=context)

    assert len(compiled.steps) == 5
    reader_step = compiled.steps[0]
    analysis_step, validation_step, content_step = compiled.steps[1:4]
    template_step = compiled.steps[4]
    assert reader_step.input_source == InputSource.FLOW_INPUT
    assert reader_step.input_type == InputType.DOCUMENT
    assert reader_step.output_type == OutputType.JSON
    assert reader_step.output_contract is not None
    assert sorted(reader_step.output_contract["properties"]) == [
        "source_facts",
        "uncertainties",
    ]
    assert reader_step.input_config is not None
    runtime_input = reader_step.input_config["runtime_input"]
    assert runtime_input["enabled"] is True
    assert runtime_input["required"] is True
    assert runtime_input["max_files"] == 2
    assert runtime_input["input_format"] == "document"
    assert analysis_step.output_type == OutputType.JSON
    assert validation_step.output_type == OutputType.JSON
    assert content_step.input_source == InputSource.PREVIOUS_STEP
    assert content_step.input_type == InputType.JSON
    assert content_step.output_type == OutputType.TEXT
    assert template_step.input_source == InputSource.PREVIOUS_STEP
    assert template_step.input_type == InputType.TEXT
    assert template_step.output_type == OutputType.DOCX
    assert template_step.output_mode == OutputMode.TEMPLATE_FILL
    assert template_step.input_bindings is None
    assert template_step.output_config == {
        "bindings": {
            "step_a.output.structured.source_facts": (
                "{{ step_a.output.structured.source_facts }}"
            ),
            "step_b.output.structured.case_summary": (
                "{{ step_b.output.structured.case_summary }}"
            ),
            "step_c.output.structured.validated_summary": (
                "{{ step_c.output.structured.validated_summary }}"
            ),
            "föregående_steg": "{{ föregående_steg }}",
        }
    }

    single_step_intent = intent.model_copy(update={"steps": [intent.steps[-1]]})
    fixed_terminal = compile_create_intent_to_spec(
        single_step_intent,
        context=replace(
            context,
            selected_template_count=None,
            selected_template_placeholders=None,
        ),
    ).steps[-1]
    assert (
        template_step.model_copy(
            update={
                "plan_step_ref": fixed_terminal.plan_step_ref,
                "output_config": fixed_terminal.output_config,
            }
        )
        == fixed_terminal
    )

    critic_issue_ids = {
        issue.id
        for issue in evaluate_critic_invariants(
            build_conversation_critic_context([], compiled)
        )
    }
    assert "terminal_renderer_must_not_consume_review_only_step" not in (
        critic_issue_ids
    )
    assert "final_text_step_must_reference_relevant_structured_outputs" not in (
        critic_issue_ids
    )
    assert validate_spec(compiled).valid


def test_compiler_enforces_template_preparation_stage_limit() -> None:
    def intent_with_stage_count(stage_count: int):
        preparation_steps = [
            {
                "name": f"Prepare source facts {index}",
                "instructions": f"Prepare source facts for stage {index}.",
                "output_fields": [
                    {
                        "name": f"prepared_facts_{index}",
                        "field_type": "string",
                        "description": f"Prepared source facts from stage {index}.",
                    }
                ],
            }
            for index in range(1, stage_count)
        ]
        return parse_create_flow_intent_arguments(
            {
                "flow_name": "Template report",
                "plan_rationale": "Prepare source facts and fill the template.",
                "steps": [
                    *preparation_steps,
                    {
                        "name": "Write template content",
                        "instructions": "Write the prepared facts as template content.",
                    },
                ],
            }
        )

    context = CreateCompileContext(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.DOCX,
        final_output_mode=OutputMode.TEMPLATE_FILL,
        pattern_ids=("document_to_docx_template",),
        pattern_chain_steps=(
            FLOW_INPUT_DOCUMENT_UPLOAD,
            EXTRACT_TEMPLATE_VARIABLES_STEP,
            PREPARE_TEMPLATE_CONTENT_STEP,
            TEMPLATE_FILL_DOCX_STEP,
        ),
    )

    compiled = compile_create_intent_to_spec(
        intent_with_stage_count(5),
        context=context,
    )

    assert len(compiled.steps) == 7

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            intent_with_stage_count(6),
            context=context,
        )

    assert exc_info.value.log_context["failure_code"] == (
        "template_preparation_stage_limit_exceeded"
    )
    assert "Consolidate" in exc_info.value.detail


def test_docx_template_unsupported_shapes_keep_typed_failure_codes() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Template report",
            "plan_rationale": "Write content and fill the template.",
            "steps": [
                {
                    "name": "Write template content",
                    "instructions": "Write the template content.",
                }
            ],
        }
    )
    context = CreateCompileContext(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.DOCX,
        final_output_mode=OutputMode.TEMPLATE_FILL,
        pattern_ids=("document_to_docx_template",),
        pattern_chain_steps=(
            FLOW_INPUT_DOCUMENT_UPLOAD,
            EXTRACT_TEMPLATE_VARIABLES_STEP,
            PREPARE_TEMPLATE_CONTENT_STEP,
            TEMPLATE_FILL_DOCX_STEP,
        ),
    )

    # Cross-checking sources is preparation work inside the fixed template
    # topology, so aggregate/compare intents assemble like linear ones.
    compare_compiled = compile_create_intent_to_spec(
        intent,
        context=replace(context, aggregation_intent="compare"),
    )
    assert compare_compiled.steps[-1].output_mode == OutputMode.TEMPLATE_FILL

    compiled = compile_create_intent_to_spec(intent, context=context)
    step_after_fill = compiled.steps[-2].model_copy(
        update={"plan_step_ref": "step_after_fill"}
    )
    invalid_position = compiled.model_copy(
        update={"steps": [*compiled.steps, step_after_fill]}
    )
    with pytest.raises(AIBuilderArchitectureError) as position_exc:
        apply_template_attachment_contract(
            invalid_position,
            selected_template_count=1,
            placeholders=(),
        )
    assert position_exc.value.log_context["failure_code"] == (
        "template_fill_position_invalid"
    )


def test_compiler_accepts_docx_template_with_runtime_form_field_overlay() -> None:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "documents"),
        "terminal_output": _slot("terminal_output", "docx_document"),
        "docx_output_mode": _slot("docx_output_mode", "template_fill_docx"),
        "document_material_scope": _slot(
            "document_material_scope",
            "single_document_case",
        ),
        "runtime_metadata_fields": _slot(
            "runtime_metadata_fields",
            "detailed_runtime_metadata",
        ),
    }
    state.file_roles = [
        FileRoleEvidence(
            file_id=UUID("00000000-0000-0000-0000-000000000901"),
            filename="ärendemall.docx",
            file_type="document",
            mimetype=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            has_readable_text=True,
            coverage="fully_seen",
            role="template",
            source="heuristic",
            confidence="high",
            template_placeholders=["arendenummer"],
        )
    ]
    state.input_fields = [_confirmed_runtime_field("arendenummer", "ärendenummer")]
    state.checkpoint_intents = [
        CheckpointIntent(
            producer_kind="report_text",
            operation="set",
            mode=FlowStepReviewMode.VIEW,
            confidence="high",
            evidence=["quote:user_message:1:Review the document content."],
        )
    ]
    _commit_architecture(state)
    context = create_compile_context_from_planning_state(
        state,
        ui_language="sv",
    )
    assert context is not None
    assert context.pattern_ids == (
        "document_to_docx_template",
        "form_field_runtime_inputs",
    )

    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Mallbaserad ärenderapport",
            "plan_rationale": "Läs mallen, skriv innehållet och fyll dokumentet.",
            "steps": [
                {
                    "name": "Förbered dokumentinnehåll",
                    "instructions": "Förbered innehållet för dokumentmallen.",
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(intent, context=context)

    assert [field.name for field in compiled.form_fields or ()] == ["arendenummer"]
    reader_step, content_step, template_step = compiled.steps
    assert content_step.review_policy is not None
    assert content_step.review_policy.mode.value == "view"
    assert "arendenummer: {{ flow_input.arendenummer }}" in _question(
        content_step.input_bindings
    )
    assert "flow_input.arendenummer" not in repr(reader_step.input_bindings)
    assert (
        _question(template_step.input_bindings).count("{{ flow_input.arendenummer }}")
        == 1
    )
    assert template_step.output_mode == OutputMode.TEMPLATE_FILL
    assert template_step.output_type == OutputType.DOCX
    assert validate_spec(compiled).valid


def test_docx_template_placeholders_become_server_owned_form_fields() -> None:
    state = PlanningState.empty()
    state.resolved_slots["terminal_output"] = _slot(
        "terminal_output",
        "docx_document",
    )
    state.output_schema_evidence = build_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {
                "kundnamn": {"type": "string"},
                "flow_input.case_id": {"type": "string"},
                "datum": {"type": "string"},
                "step_a.output.summary": {"type": "string"},
                "text": {"type": "string"},
            },
        },
        source="template_placeholders",
        source_file_ids=("00000000-0000-0000-0000-000000000001",),
        confidence="high",
        evidence=[
            "file:file_id:content:template_placeholder:kundnamn",
            "file:file_id:content:template_placeholder:flow_input.case_id",
            "file:file_id:content:template_placeholder:datum",
            "file:file_id:content:template_placeholder:step_a.output.summary",
            "file:file_id:content:template_placeholder:text",
        ],
    )
    derived_context = create_compile_context_from_planning_state(state)
    assert derived_context is not None

    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Template report",
            "flow_description": "Fill a DOCX template from source documents.",
            "plan_rationale": "Prepare content and fill the template.",
            "steps": [
                {
                    "name": "Prepare template content",
                    "instructions": "Prepare the content for the DOCX template.",
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.DOCX,
            final_output_mode=OutputMode.TEMPLATE_FILL,
            pattern_ids=("document_to_docx_template",),
            pattern_chain_steps=(
                FLOW_INPUT_DOCUMENT_UPLOAD,
                EXTRACT_TEMPLATE_VARIABLES_STEP,
                TEMPLATE_FILL_DOCX_STEP,
            ),
            template_placeholder_field_hints=(
                derived_context.template_placeholder_field_hints
            ),
            selected_template_count=1,
            selected_template_placeholders=(
                "kundnamn",
                "flow_input.case_id",
            ),
        ),
    )

    assert compiled.form_fields is not None
    assert [field.name for field in compiled.form_fields] == ["kundnamn", "case_id"]
    content_step = compiled.steps[1]
    assert content_step.input_bindings is None
    template_question = _question(compiled.steps[-1].input_bindings)
    assert "kundnamn: {{ flow_input.kundnamn }}" in template_question
    assert "case_id: {{ flow_input.case_id }}" in template_question
    assert validate_spec(compiled).valid


def test_compiler_lowers_runtime_inputs_and_derived_whole_object_underlag() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Dokumentanalys",
            "plan_rationale": "Extrahera risker och skriv slutrapport.",
            "steps": [
                {
                    "name": "Extrahera risker",
                    "instructions": "Extrahera risker och rekommendationer.",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Kort sammanfattning.",
                        }
                    ],
                },
                {
                    "name": "Skriv slutrapport",
                    "instructions": "Skriv slutrapport med specifika datapunkter.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.TEXT,
            runtime_max_files=5,
            runtime_input_fields=(
                _confirmed_runtime_field(
                    "referensnummer", "Referensnummer", required=True
                ),
            ),
        ),
    )

    first_step = compiled.steps[0]
    assert compiled.form_fields is not None
    assert [field.name for field in compiled.form_fields] == ["referensnummer"]
    assert first_step.input_config is not None
    runtime_input = first_step.input_config["runtime_input"]
    assert runtime_input["enabled"] is True
    assert runtime_input["required"] is True
    assert runtime_input["max_files"] == 5
    assert runtime_input["input_format"] == "document"
    assert _question(first_step.input_bindings) == (
        "{{ step_input.text }}\n\nreferensnummer: {{ flow_input.referensnummer }}"
    )
    assert compiled.steps[1].input_bindings == {
        "source_refs": [{"step_ref": "step_a", "output": "structured"}]
    }
    assert validate_spec(compiled).valid


@pytest.mark.parametrize("final_output_type", [OutputType.PDF, OutputType.DOCX])
def test_document_artifact_keeps_body_writer_before_render_verbatim_renderer(
    final_output_type: OutputType,
) -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Document artifact report",
            "plan_rationale": "Extract facts, analyze them, and render a document.",
            "steps": [
                {
                    "name": "Extract source facts",
                    "instructions": "Extract document type, date, author, and conclusions.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "Structured facts per document.",
                        }
                    ],
                },
                {
                    "name": "Analyze document meaning",
                    "instructions": "Analyze the extracted document facts.",
                    "output_fields": [
                        {
                            "name": "analysis",
                            "field_type": "string",
                            "description": "Interpretation of the document facts.",
                        }
                    ],
                },
                {
                    "name": "Write report body",
                    "instructions": "Write the final report body from all structured work.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=final_output_type,
            final_output_mode=OutputMode.PASS_THROUGH,
            aggregation_intent=cast(AggregationIntent, "aggregate"),
        ),
    )

    body_step = compiled.steps[-2]
    renderer_step = compiled.steps[-1]
    assert [step.output_type for step in compiled.steps] == [
        OutputType.JSON,
        OutputType.JSON,
        OutputType.TEXT,
        final_output_type,
    ]
    assert body_step.name == "Write report body"
    assert renderer_step.input_source == InputSource.PREVIOUS_STEP
    assert renderer_step.input_type == InputType.TEXT
    assert renderer_step.output_mode == OutputMode.RENDER_VERBATIM
    assert renderer_step.input_bindings is None
    assert compiled.document_body_writer_step_refs == (body_step.plan_step_ref,)
    assert validate_spec(compiled).valid


@pytest.mark.parametrize(
    ("helper_name", "helper_instructions"),
    [
        (
            "Formatera slutrapporten",
            "Omvandla den färdiga rapporttexten till en professionell PDF "
            "med tydlig struktur och läsbar layout.",
        ),
        ("Skapa PDF-rapport", "Skapa slutrapporten från den färdiga rapporttexten."),
    ],
)
def test_document_artifact_drops_explicit_pdf_render_helper(
    helper_name: str,
    helper_instructions: str,
) -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Dokumentanalys till PDF",
            "plan_rationale": (
                "Läs dokument, skriv rapportinnehåll och leverera som PDF."
            ),
            "steps": [
                {
                    "name": "Identifiera dokumentens innehåll",
                    "instructions": (
                        "Läs varje inskickat dokument och avgör vad det är för "
                        "typ av dokument, vilket ämne det handlar om, kategori, "
                        "datum, författare och slutsatser."
                    ),
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": (
                                "En post per dokument i körningen med de uppgifter "
                                "som ska användas i rapporten."
                            ),
                        }
                    ],
                },
                {
                    "name": "Skriv rapportinnehåll",
                    "instructions": (
                        "Använd den extraherade informationen för att skriva den "
                        "fullständiga rapporttexten för PDF:en. Presentera varje "
                        "dokument tydligt med titel, år, kategori, dokumenttyp, "
                        "författare, slutsatser och en kort sammanfattning."
                    ),
                },
                {
                    "name": helper_name,
                    "instructions": helper_instructions,
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.PASS_THROUGH,
            aggregation_intent=cast(AggregationIntent, "linear"),
        ),
    )

    assert [step.name for step in compiled.steps] == [
        "Identifiera dokumentens innehåll",
        "Skriv rapportinnehåll",
        "Rendera PDF",
    ]
    assert [step.output_type for step in compiled.steps] == [
        OutputType.JSON,
        OutputType.TEXT,
        OutputType.PDF,
    ]
    body_step = compiled.steps[-2]
    renderer_step = compiled.steps[-1]
    assert renderer_step.input_source == InputSource.PREVIOUS_STEP
    assert renderer_step.input_type == InputType.TEXT
    assert renderer_step.output_mode == OutputMode.RENDER_VERBATIM
    assert renderer_step.input_bindings is None
    assert renderer_step.plan_step_ref != body_step.plan_step_ref
    assert compiled.document_body_writer_step_refs == (body_step.plan_step_ref,)
    assert validate_spec(compiled).valid


def test_document_artifact_folds_terminal_helper_fields_into_body_writer() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Dokumentanalys till PDF",
            "plan_rationale": (
                "Läs dokument, skriv rapportinnehåll och leverera som PDF."
            ),
            "steps": [
                {
                    "name": "Identifiera dokumentens innehåll",
                    "instructions": "Läs dokumenten och extrahera källfakta.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "Dokumentfakta per fil.",
                        }
                    ],
                },
                {
                    "name": "Skriv rapportinnehåll",
                    "instructions": "Skriv den fullständiga rapporttexten.",
                },
                {
                    "name": "Skapa PDF-rapport",
                    "instructions": "Skapa slutrapporten som PDF.",
                    "output_fields": [
                        {
                            "name": "author_or_source",
                            "field_type": "string",
                            "description": "Vem som skrev dokumentet.",
                        },
                        {
                            "name": "conclusions",
                            "field_type": "array",
                            "description": "Dokumentets slutsatser.",
                        },
                    ],
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.PASS_THROUGH,
            aggregation_intent=cast(AggregationIntent, "linear"),
        ),
    )

    assert [step.name for step in compiled.steps] == [
        "Identifiera dokumentens innehåll",
        "Skriv rapportinnehåll",
        "Rendera PDF",
    ]
    body_step = compiled.steps[-2]
    renderer_step = compiled.steps[-1]
    assert body_step.output_type == OutputType.TEXT
    # The fold carries field MEANINGS, never machine keys — raw keys in a
    # prose instruction invited JSON-envelope answers (live run 4fc4b445).
    assert "Vem som skrev dokumentet" in body_step.assistant_spec.instructions
    assert "author_or_source" not in body_step.assistant_spec.instructions
    assert "aldrig som JSON" in body_step.assistant_spec.instructions
    assert "Dokumentets slutsatser" in body_step.assistant_spec.instructions
    assert renderer_step.output_type == OutputType.PDF
    assert renderer_step.output_mode == OutputMode.RENDER_VERBATIM
    assert validate_spec(compiled).valid


def test_document_reader_contract_canonicalizes_items_and_source_scope() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Dokumentanalys till PDF",
            "plan_rationale": "Läs dokument och skriv en PDF-rapport.",
            "steps": [
                {
                    "name": "Identifiera dokumentens innehåll",
                    "instructions": "Läs varje dokument och strukturera fakta.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "En post per dokument.",
                            "item_fields": [
                                {
                                    "name": "title",
                                    "field_type": "string",
                                    "description": "Dokumenttitel.",
                                },
                                {
                                    "name": "date",
                                    "field_type": "string",
                                    "description": "Datum eller år.",
                                },
                                {
                                    "name": "author",
                                    "field_type": "string",
                                    "description": "Författare.",
                                },
                                {
                                    "name": "summary",
                                    "field_type": "string",
                                    "description": "Sammanfattning.",
                                },
                                {
                                    "name": "brief_summary",
                                    "field_type": "string",
                                    "description": "Duplicerad sammanfattning.",
                                },
                                {
                                    "name": "documents",
                                    "field_type": "string",
                                    "description": "Felaktig nästlad container.",
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Skriv rapportinnehåll",
                    "instructions": "Skriv rapporten.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.PASS_THROUGH,
            runtime_max_files=4,
            aggregation_intent=cast(AggregationIntent, "linear"),
            ui_language="sv",
            report_disposition="both",
        ),
    )

    reader_step = compiled.steps[0]
    section_step = compiled.steps[1]
    assert reader_step.output_contract is not None
    documents_schema = reader_step.output_contract["properties"]["documents"]
    item_properties = documents_schema["items"]["properties"]
    assert list(item_properties) == [
        "source_label",
        "source_file_id",
        "title",
        "date",
        "author",
        "summary",
    ]
    assert "documents" not in item_properties
    reader_instructions = reader_step.assistant_spec.instructions
    assert "körs en gång per uppladdad källa" in reader_instructions
    assert "source_label" not in reader_instructions
    assert "source_file_id" not in reader_instructions
    assert (
        "Allowed fields for items of documents: title, date, author, summary."
    ) in reader_instructions
    assert (
        "Allowed fields for items of documents: source_label" not in reader_instructions
    )
    assert "file_name" not in reader_instructions
    assert reader_step.input_config is not None
    assert reader_step.input_config["runtime_input"]["execution_mode"] == "per_source"
    assert '"Källa: {source_label}"' not in section_step.assistant_spec.instructions
    assert (
        "section_title"
        in section_step.output_contract["properties"]["source_sections"]["items"][
            "properties"
        ]
    )
    assert compiled.steps[-2].output_mode == OutputMode.COMPOSE_TEXT
    assert validate_spec(compiled).valid


def test_report_disposition_both_uses_deterministic_compose_topology() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Rapport över dokument",
            "plan_rationale": "Läs källor, skriv källavsnitt och slutrapport.",
            "steps": [
                {
                    "name": "Läs dokumenten",
                    "instructions": "Läs varje dokument och strukturera fakta.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "En post per dokument.",
                            "item_fields": [
                                {
                                    "name": "title",
                                    "field_type": "string",
                                    "description": "Titel.",
                                },
                                {
                                    "name": "summary",
                                    "field_type": "string",
                                    "description": "Sammanfattning.",
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Bygg källavsnitt",
                    "instructions": "Skriv ett rapportavsnitt per källa.",
                    "output_fields": [
                        {
                            "name": "source_sections",
                            "field_type": "array",
                            "description": "Avsnitt per källa.",
                            "item_fields": [
                                {
                                    "name": "section_title",
                                    "field_type": "string",
                                    "description": "Avsnittsrubrik.",
                                },
                                {
                                    "name": "section_body",
                                    "field_type": "string",
                                    "description": "Färdig avsnittstext.",
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Skriv översikt",
                    "instructions": "Skriv en samlad översikt över alla källor.",
                    "output_fields": [
                        {
                            "name": "overview",
                            "field_type": "string",
                            "description": "Samlad översikt.",
                        }
                    ],
                },
                {
                    "name": "Sätt ihop slutrapport",
                    "instructions": "Sätt ihop slutrapporten.",
                    "model_ref": "model.report-writer",
                    "knowledge_refs": ["knowledge.reporting-policy"],
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.PASS_THROUGH,
            runtime_max_files=4,
            aggregation_intent=cast(AggregationIntent, "aggregate"),
            ui_language="sv",
            report_disposition="both",
            runtime_input_fields=(
                _confirmed_runtime_field(
                    "case_number", "Case number", purpose="shape_result"
                ),
            ),
        ),
    )

    assert [step.name for step in compiled.steps] == [
        "Läs dokumenten",
        "Bygg källavsnitt",
        "Skriv översikt",
        "Sätt ihop slutrapport",
        "Rendera PDF",
    ]
    section_step = compiled.steps[1]
    assert section_step.input_config == {"item_map": {"enabled": True, "max_items": 4}}
    assert "körs en gång per documents[]-post" in (
        section_step.assistant_spec.instructions
    )
    section_properties = section_step.output_contract["properties"]["source_sections"][
        "items"
    ]["properties"]
    assert "section_title" in section_properties
    assert "section_body" in section_properties
    assert "source_label" in section_properties
    assert "source_file_id" in section_properties

    overview_step = compiled.steps[2]
    assert overview_step.output_contract is not None
    assert list(overview_step.output_contract["properties"]) == [
        "report_title",
        "overall_overview",
    ]
    assert "Sätt ihop slutrapporten." in overview_step.assistant_spec.instructions
    assert overview_step.assistant_spec.model_ref == "model.report-writer"
    assert overview_step.assistant_spec.knowledge_refs == ["knowledge.reporting-policy"]
    assert "{{ flow_input.case_number }}" in _question(overview_step.input_bindings)

    body_writer_step = compiled.steps[3]
    assert body_writer_step.input_source == InputSource.PREVIOUS_STEP
    assert body_writer_step.output_mode == OutputMode.COMPOSE_TEXT
    assert body_writer_step.input_bindings is not None
    assert "flow_input.case_number" not in _question(body_writer_step.input_bindings)
    assert body_writer_step.review_policy is None
    assert body_writer_step.input_bindings["source_refs"] == [
        {
            "step_ref": "step_b",
            "output": "structured",
            "field_path": "source_sections",
            "item_template": (
                "## {section_title}\n\n{section_body}\n\nKälla: {source_label}"
            ),
        },
        {
            "step_ref": "step_c",
            "output": "structured",
            "field_path": "overall_overview",
            "label": "Samlad översikt",
        },
    ]
    assert all(
        step.input_source != InputSource.ALL_PREVIOUS_STEPS for step in compiled.steps
    )
    validation = validate_spec(compiled)
    assert validation.valid, validation.errors


@pytest.mark.parametrize(
    "report_disposition",
    ["per_source_sections", "synthesized_overview", "both"],
)
def test_report_lowering_converts_intermediate_text_writer_without_repair(
    report_disposition: ReportDisposition,
) -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Source report",
            "plan_rationale": "Extract evidence, draft the findings, and render them.",
            "steps": [
                {
                    "name": "Extract evidence",
                    "instructions": "Extract grounded evidence from each source.",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Grounded source summary.",
                        }
                    ],
                },
                {
                    "name": "Draft findings",
                    "instructions": "Draft the evidence-backed findings.",
                },
                {
                    "name": "Refine findings",
                    "instructions": "Refine the findings without losing source evidence.",
                },
                {
                    "name": "Write report",
                    "instructions": "Write the complete final report.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            aggregation_intent="linear",
            report_disposition=report_disposition,
            runtime_max_files=4,
            ui_language="en",
        ),
    )

    instructions = "\n".join(
        step.assistant_spec.instructions for step in compiled.steps
    )
    assert "Draft the evidence-backed findings." in instructions
    assert "Refine the findings without losing source evidence." in instructions
    assert "Write the complete final report." in instructions
    assert "documents" in compiled.steps[0].output_contract["properties"]
    assert compiled.steps[-2].output_mode == OutputMode.COMPOSE_TEXT
    assert compiled.steps[-1].output_mode == OutputMode.RENDER_VERBATIM
    validation = validate_spec(compiled)
    assert validation.valid, validation.errors


def test_per_source_requested_section_label_stays_with_canonical_producer() -> None:
    requested_sections = RequestedOutputSections(
        sections=("Résumé",),
        confidence="high",
    )
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Source risk report",
            "plan_rationale": "Build source sections and assess their risks.",
            "steps": [
                {
                    "name": "Read documents",
                    "instructions": "Extract source-grounded evidence.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "One record per source.",
                            "item_fields": [
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
                    "name": "Build source sections",
                    "instructions": "Write one report section per source.",
                    "output_fields": [
                        {
                            "name": "source_sections",
                            "field_type": "array",
                            "description": "Finished source sections.",
                            "item_fields": [
                                {
                                    "name": "section_title",
                                    "field_type": "string",
                                    "description": "Section title.",
                                },
                                {
                                    "name": "section_body",
                                    "field_type": "string",
                                    "description": "Section body.",
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Assess risks",
                    "instructions": "Assess risks across the source sections.",
                    "output_fields": [
                        {
                            "name": "requested_section_1",
                            "field_type": "string",
                            "description": "Cross-source risk assessment.",
                        }
                    ],
                },
                {
                    "name": "Compose report",
                    "instructions": "Compose the complete report.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            report_disposition="per_source_sections",
            requested_output_sections=requested_sections,
            runtime_max_files=4,
            ui_language="en",
        ),
    )

    compose_bindings = compiled.steps[-2].input_bindings
    assert compose_bindings is not None
    assert {
        (ref["step_ref"], ref["field_path"]) for ref in compose_bindings["source_refs"]
    } == {
        ("step_b", "source_sections"),
        ("step_c", "requested_section_1"),
    }
    canonical_ref, independent_ref = compose_bindings["source_refs"]
    assert "Résumé: {requested_section_1}" in canonical_ref["item_template"]
    assert independent_ref["label"] == "Requested section 1"
    assert validate_spec(compiled).valid

    corrupt_canonical_ref = dict(canonical_ref)
    corrupt_canonical_ref["item_template"] = canonical_ref["item_template"].replace(
        "Résumé: {requested_section_1}",
        "Other section: {requested_section_1}",
    )
    corrupt_independent_ref = dict(independent_ref)
    corrupt_independent_ref["label"] = "Résumé"
    corrupt_compose = compiled.steps[-2].model_copy(
        update={
            "input_bindings": {
                **compose_bindings,
                "source_refs": [corrupt_canonical_ref, corrupt_independent_ref],
            }
        }
    )
    corrupt_spec = compiled.model_copy(
        update={"steps": [*compiled.steps[:-2], corrupt_compose, compiled.steps[-1]]}
    )
    assert validate_spec(corrupt_spec).valid
    corrupt_issue_ids = {
        issue.id
        for issue in evaluate_critic_invariants(
            build_conversation_critic_context(
                [],
                corrupt_spec,
                requested_output_sections=requested_sections,
            )
        )
    }
    assert "requested_output_sections_require_section_writers" in corrupt_issue_ids


def test_per_source_report_keeps_first_section_producer_canonical() -> None:
    requested_sections = RequestedOutputSections(
        sections=("Résumé",),
        confidence="high",
    )
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Refined source report",
            "plan_rationale": "Build source sections and refine them independently.",
            "steps": [
                {
                    "name": "Read documents",
                    "instructions": "Extract source-grounded evidence.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "One record per source.",
                            "item_fields": [
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
                    "name": "Build source sections",
                    "instructions": "Write one report section per source.",
                    "output_fields": [
                        {
                            "name": "source_sections",
                            "field_type": "array",
                            "description": "Finished source sections.",
                            "item_fields": [
                                {
                                    "name": "section_title",
                                    "field_type": "string",
                                    "description": "Section title.",
                                },
                                {
                                    "name": "section_body",
                                    "field_type": "string",
                                    "description": "Section body.",
                                },
                                {
                                    "name": "source_label",
                                    "field_type": "string",
                                    "description": "Source label.",
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Refine sections",
                    "instructions": "Refine the source sections independently.",
                    "output_fields": [
                        {
                            "name": "refined_sections",
                            "field_type": "array",
                            "description": "Independent refined sections.",
                            "item_fields": [
                                {
                                    "name": "section_title",
                                    "field_type": "string",
                                    "description": "Refined section title.",
                                },
                                {
                                    "name": "section_body",
                                    "field_type": "string",
                                    "description": "Refined section body.",
                                },
                                {
                                    "name": "source_label",
                                    "field_type": "string",
                                    "description": "Source label.",
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Compose report",
                    "instructions": "Compose the complete report.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            report_disposition="per_source_sections",
            requested_output_sections=requested_sections,
            runtime_max_files=4,
            ui_language="en",
        ),
    )

    compose_refs = source_ref_bindings(compiled.steps[-2].input_bindings)
    assert [(ref.step_ref, ref.field_path) for ref in compose_refs] == [
        ("step_b", ("source_sections",)),
        ("step_c", ("refined_sections",)),
    ]
    assert compose_refs[0].item_template is not None
    assert "Résumé: {requested_section_1}" in compose_refs[0].item_template
    assert validate_spec(compiled).valid
    issues = evaluate_critic_invariants(
        build_conversation_critic_context(
            [],
            compiled,
            requested_output_sections=requested_sections,
        )
    )
    assert not issues


@pytest.mark.parametrize("runtime_max_files", [None, 1])
def test_single_call_custom_section_array_guidance_uses_selected_field(
    runtime_max_files: int | None,
) -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Source chapters",
            "plan_rationale": "Build one chapter per source.",
            "steps": [
                {
                    "name": "Read documents",
                    "instructions": "Extract source-grounded evidence.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "One record per source.",
                            "item_fields": [
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
                    "name": "Build chapters",
                    "instructions": "Build one report chapter per source.",
                    "output_fields": [
                        {
                            "name": "chapters",
                            "field_type": "array",
                            "description": "Finished report chapters.",
                            "item_fields": [
                                {
                                    "name": "section_title",
                                    "field_type": "string",
                                    "description": "Chapter title.",
                                },
                                {
                                    "name": "section_body",
                                    "field_type": "string",
                                    "description": "Chapter body.",
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Compose report",
                    "instructions": "Compose the complete report.",
                },
            ],
        }
    )
    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            report_disposition="per_source_sections",
            runtime_max_files=runtime_max_files,
            ui_language="en",
        ),
    )

    compose_refs = compiled.steps[-2].input_bindings["source_refs"]
    assert compose_refs[0]["field_path"] == "chapters"
    section_instructions = compiled.steps[1].assistant_spec.instructions
    assert "one chapters item" in section_instructions
    assert "source_sections" not in section_instructions
    assert validate_spec(compiled).valid


def test_create_intent_rejects_fields_outside_structured_contract() -> None:
    # Separator styles fold to a valid identifier instead of rejecting.
    folded = parse_create_flow_intent_arguments(
        {
            "flow_name": "Folded field name",
            "plan_rationale": "Exercise the typed structured-field boundary.",
            "steps": [
                {
                    "name": "Extract risks",
                    "instructions": "Extract the risks.",
                    "output_fields": [
                        {
                            "name": "risk-level",
                            "field_type": "string",
                            "description": "Risk level.",
                        }
                    ],
                }
            ],
        }
    )
    assert [field.name for field in folded.steps[0].output_fields or []] == [
        "risk_level"
    ]

    with pytest.raises(
        ProposalIntentArgumentError,
        match="structured field names must be ASCII identifiers",
    ):
        parse_create_flow_intent_arguments(
            {
                "flow_name": "Invalid field name",
                "plan_rationale": "Exercise the typed structured-field boundary.",
                "steps": [
                    {
                        "name": "Extract risks",
                        "instructions": "Extract the risks.",
                        "output_fields": [
                            {
                                "name": "123",
                                "field_type": "string",
                                "description": "Risk level.",
                            }
                        ],
                    }
                ],
            }
        )

    with pytest.raises(
        ProposalIntentArgumentError,
        match="structured field descriptions must not contain template variables",
    ):
        parse_create_flow_intent_arguments(
            {
                "flow_name": "Invalid field description",
                "plan_rationale": "Exercise the typed structured-field boundary.",
                "steps": [
                    {
                        "name": "Extract risks",
                        "instructions": "Extract the risks.",
                        "output_fields": [
                            {
                                "name": "risk_level",
                                "field_type": "string",
                                "description": "Risk from {{source}}.",
                            }
                        ],
                    }
                ],
            }
        )


def test_report_lowering_normalizes_canonical_field_shapes_and_overview_alias() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Canonical report",
            "plan_rationale": "Build sections and a synthesized overview.",
            "steps": [
                {
                    "name": "Read sources",
                    "instructions": "Extract one record per source.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "One record per source.",
                            "item_fields": [
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
                    "name": "Build sections",
                    "instructions": "Build one section per source.",
                    "output_fields": [
                        {
                            "name": "source_sections",
                            "field_type": "array",
                            "description": "Report sections.",
                            "item_fields": [
                                {
                                    "name": "section_title",
                                    "field_type": "array",
                                    "description": "Invalid title shape.",
                                    "item_fields": [
                                        {
                                            "name": "value",
                                            "field_type": "string",
                                            "description": "Title value.",
                                        }
                                    ],
                                },
                                {
                                    "name": "section_body",
                                    "field_type": "array",
                                    "description": "Invalid body shape.",
                                    "item_fields": [
                                        {
                                            "name": "value",
                                            "field_type": "string",
                                            "description": "Body value.",
                                        }
                                    ],
                                },
                                {
                                    "name": "open_questions",
                                    "field_type": "string",
                                    "description": "Questions about {source}.",
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Write overview",
                    "instructions": "Write the report overview.",
                    "output_fields": [
                        {
                            "name": "report_title",
                            "field_type": "array",
                            "description": "Invalid report title shape.",
                            "item_fields": [
                                {
                                    "name": "value",
                                    "field_type": "string",
                                    "description": "Title value.",
                                }
                            ],
                        },
                        {
                            "name": "overview",
                            "field_type": "string",
                            "description": "Existing overview alias.",
                        },
                        {
                            "name": "key_points",
                            "field_type": "array",
                            "description": "Key report points.",
                            "item_fields": [
                                {
                                    "name": "point",
                                    "field_type": "string",
                                    "description": "One report point.",
                                }
                            ],
                        },
                        {
                            "name": "report_metadata",
                            "field_type": "object",
                            "description": "Report metadata.",
                            "fields": [
                                {
                                    "name": "owner",
                                    "field_type": "string",
                                    "description": "Report owner.",
                                }
                            ],
                        },
                        {
                            "name": "confidence",
                            "field_type": "number",
                            "description": "Report confidence.",
                        },
                        {
                            "name": "tags",
                            "field_type": "array",
                            "description": "Report tags.",
                        },
                    ],
                },
                {
                    "name": "Compose report",
                    "instructions": "Compose the final report.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            aggregation_intent="linear",
            report_disposition="both",
            runtime_max_files=4,
            ui_language="en",
        ),
    )

    section_properties = compiled.steps[1].output_contract["properties"][
        "source_sections"
    ]["items"]["properties"]
    assert section_properties["section_title"]["type"] == "string"
    assert section_properties["section_body"]["type"] == "string"
    overview_properties = compiled.steps[2].output_contract["properties"]
    assert overview_properties["report_title"]["type"] == "string"
    assert overview_properties["overall_overview"]["type"] == "string"
    assert "overview" not in overview_properties
    compose_bindings = str(compiled.steps[-2].input_bindings)
    assert compose_bindings.count("overall_overview") == 1
    assert "Open questions: {open_questions}" in compose_bindings
    assert "Point: {point}" in compose_bindings
    assert "report_metadata" in compose_bindings
    assert "confidence" in compose_bindings
    assert "tags" in compose_bindings
    validation = validate_spec(compiled)
    assert validation.valid, validation.errors


def test_report_lowering_combines_json_overview_models_once_and_uses_terminal_model() -> (
    None
):
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Conflicting report models",
            "plan_rationale": "Use a structured overview before composition.",
            "steps": [
                {
                    "name": "Read source",
                    "instructions": "Extract source evidence.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "Source evidence.",
                            "item_fields": [
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
                    "name": "Write overview",
                    "instructions": "Write the overview.",
                    "model_ref": "model.overview",
                    "output_fields": [
                        {
                            "name": "overall_conclusion",
                            "field_type": "string",
                            "description": "Overall conclusion.",
                        }
                    ],
                },
                {
                    "name": "Compose report",
                    "instructions": "Compose the final report.",
                    "model_ref": "model.body",
                },
            ],
        }
    )

    diagnostics = []
    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            aggregation_intent="linear",
            report_disposition="synthesized_overview",
            runtime_max_files=4,
            ui_language="en",
        ),
        field_diagnostics=diagnostics,
    )

    assert compiled.steps[1].assistant_spec.model_ref == "model.body"
    assert [warning.code for warning in diagnostics] == [
        "document_report_model_selection_combined"
    ]
    assert [warning.message for warning in diagnostics] == [
        "The steps specified different model selections; they were combined and "
        "the combined report-writing step uses model selection model.body."
    ]
    validation = validate_spec(compiled)
    assert validation.valid, validation.errors


def test_per_source_sections_combines_distinct_models_once_and_uses_terminal_model() -> (
    None
):
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Conflicting report models",
            "plan_rationale": "Combine report-writing semantics before composition.",
            "steps": [
                {
                    "name": "Read source",
                    "instructions": "Extract source evidence.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "Source evidence.",
                            "item_fields": [
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
                    "name": "Refine report",
                    "instructions": "Refine the report.",
                    "model_ref": "model.refine",
                },
                {
                    "name": "Compose report",
                    "instructions": "Compose the final report.",
                    "model_ref": "model.body",
                },
            ],
        }
    )

    diagnostics = []
    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            aggregation_intent="linear",
            report_disposition="per_source_sections",
            runtime_max_files=4,
            ui_language="en",
        ),
        field_diagnostics=diagnostics,
    )

    assert compiled.steps[1].assistant_spec.model_ref == "model.body"
    assert [warning.code for warning in diagnostics] == [
        "document_report_model_selection_combined"
    ]
    assert [warning.message for warning in diagnostics] == [
        "The steps specified different model selections; they were combined and "
        "the combined report-writing step uses model selection model.body."
    ]
    validation = validate_spec(compiled)
    assert validation.valid, validation.errors


def test_report_disposition_both_preserves_distinct_producer_model_selections() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Report with sections and overview",
            "plan_rationale": "Write source sections and a synthesized overview.",
            "steps": [
                {
                    "name": "Read sources",
                    "instructions": "Extract source evidence.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "Source evidence.",
                            "item_fields": [
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
                    "name": "Write source sections",
                    "instructions": "Write one section per source.",
                    "model_ref": "model.sections",
                    "output_fields": [
                        {
                            "name": "section_text",
                            "field_type": "string",
                            "description": "Source section text.",
                        }
                    ],
                },
                {
                    "name": "Draft overview",
                    "instructions": "Draft the synthesized overview.",
                    "model_ref": "model.draft",
                    "output_fields": [
                        {
                            "name": "overview",
                            "field_type": "string",
                            "description": "Synthesized overview.",
                        }
                    ],
                },
                {
                    "name": "Compose report",
                    "instructions": "Compose the final report.",
                    "model_ref": "model.overview",
                },
            ],
        }
    )

    diagnostics = []
    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            aggregation_intent="aggregate",
            report_disposition="both",
            runtime_max_files=4,
            ui_language="en",
        ),
        field_diagnostics=diagnostics,
    )

    assert compiled.steps[1].assistant_spec.model_ref == "model.sections"
    assert compiled.steps[2].assistant_spec.model_ref == "model.overview"
    assert [warning.code for warning in diagnostics] == [
        "document_report_model_selection_combined"
    ]
    assert [warning.message for warning in diagnostics] == [
        "The steps specified different model selections; they were combined and "
        "the combined report-writing step uses model selection model.overview."
    ]
    validation = validate_spec(compiled)
    assert validation.valid, validation.errors


@pytest.mark.parametrize(
    ("draft_model_ref", "body_model_ref"),
    [
        ("model.shared", "model.shared"),
        (None, "model.only"),
    ],
)
def test_report_lowering_does_not_warn_for_compatible_model_selections(
    draft_model_ref: str | None,
    body_model_ref: str,
) -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Compatible report models",
            "plan_rationale": "Combine compatible report-writing semantics.",
            "steps": [
                {
                    "name": "Read source",
                    "instructions": "Extract source evidence.",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Source summary.",
                        }
                    ],
                },
                {
                    "name": "Draft report",
                    "instructions": "Draft the report.",
                    "model_ref": draft_model_ref,
                },
                {
                    "name": "Compose report",
                    "instructions": "Compose the final report.",
                    "model_ref": body_model_ref,
                },
            ],
        }
    )

    diagnostics = []
    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            report_disposition="synthesized_overview",
            ui_language="en",
        ),
        field_diagnostics=diagnostics,
    )

    assert compiled.steps[1].assistant_spec.model_ref == body_model_ref
    assert diagnostics == []


def test_report_lowering_emits_citation_and_model_selection_warnings() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Cited source report",
            "plan_rationale": "Create a report with citation sidecars.",
            "steps": [
                {
                    "name": "Extract cited evidence",
                    "instructions": "Extract evidence with citations.",
                    "citations_requested": True,
                    "model_ref": "model.reader",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Source summary.",
                        }
                    ],
                },
                {
                    "name": "Draft cited report",
                    "instructions": "Draft the report with citations.",
                    "citations_requested": True,
                    "model_ref": "model.draft",
                },
                {
                    "name": "Write cited report",
                    "instructions": "Write the report with citations.",
                    "model_ref": "model.body",
                },
            ],
        }
    )

    diagnostics = []
    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            report_disposition="synthesized_overview",
            ui_language="en",
        ),
        field_diagnostics=diagnostics,
    )

    assert all(
        step.output_config != {"citation_mode": "inline_inref_sidecar"}
        for step in compiled.steps
    )
    assert [warning.code for warning in diagnostics] == [
        "document_report_model_selection_combined",
        "citation_mode_unsupported",
    ]
    assert [warning.message for warning in diagnostics] == [
        "The steps specified different model selections; they were combined and "
        "the combined report-writing step uses model selection model.body.",
        "Source citations were disabled because the output cannot include "
        "inline citations.",
    ]


def test_structured_text_citations_keep_sidecar_without_downgrade() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Cited text",
            "plan_rationale": "Write cited structured text.",
            "steps": [
                {
                    "name": "Write cited text",
                    "instructions": "Write the text with citations.",
                    "citations_requested": True,
                }
            ],
        }
    )

    diagnostics = []
    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.TEXT,
            final_output_type=OutputType.TEXT,
            ui_language="en",
        ),
        field_diagnostics=diagnostics,
    )

    assert [step.output_config for step in compiled.steps] == [
        {"citation_mode": "inline_inref_sidecar"}
    ]
    assert diagnostics == []


def test_structured_json_citations_are_downgraded_before_flow_validation() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Structured record",
            "plan_rationale": "Extract a structured record.",
            "steps": [
                {
                    "name": "Extract record",
                    "instructions": "Extract the requested fields.",
                    "citations_requested": True,
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Source summary.",
                        }
                    ],
                }
            ],
        }
    )

    diagnostics = []
    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.TEXT,
            final_output_type=OutputType.JSON,
            ui_language="en",
        ),
        field_diagnostics=diagnostics,
    )

    assert validate_spec(compiled).valid
    assert compiled.steps[0].output_config is None
    assert [(warning.code, warning.message) for warning in diagnostics] == [
        (
            "citation_mode_unsupported",
            "Source citations were disabled because the output cannot include "
            "inline citations.",
        )
    ]


def test_report_disposition_both_ignores_source_section_name_without_shape() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Rapport över dokument",
            "plan_rationale": "Läs källor, skriv fria källtexter och slutrapport.",
            "steps": [
                {
                    "name": "Läs dokumenten",
                    "instructions": "Läs varje dokument och strukturera fakta.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "En post per dokument.",
                            "item_fields": [
                                {
                                    "name": "title",
                                    "field_type": "string",
                                    "description": "Titel.",
                                },
                                {
                                    "name": "summary",
                                    "field_type": "string",
                                    "description": "Sammanfattning.",
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Skriv fria källtexter",
                    "instructions": "Skriv källtexter.",
                    "output_fields": [
                        {
                            "name": "source_sections",
                            "field_type": "array",
                            "description": "Avsnitt per källa.",
                            "item_fields": [
                                {
                                    "name": "section_text",
                                    "field_type": "string",
                                    "description": "Färdig avsnittstext.",
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "Sätt ihop slutrapport",
                    "instructions": "Sätt ihop slutrapporten.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.PASS_THROUGH,
            runtime_max_files=4,
            aggregation_intent=cast(AggregationIntent, "aggregate"),
            ui_language="sv",
            report_disposition="both",
        ),
    )

    assert "Skriv fria källtexter" not in [step.name for step in compiled.steps]
    assert [step.output_mode for step in compiled.steps] == [
        OutputMode.PASS_THROUGH,
        OutputMode.PASS_THROUGH,
        OutputMode.PASS_THROUGH,
        OutputMode.COMPOSE_TEXT,
        OutputMode.RENDER_VERBATIM,
    ]
    section_step = compiled.steps[1]
    assert section_step.name == "Bygg källavsnitt"
    assert section_step.input_config == {"item_map": {"enabled": True, "max_items": 4}}
    section_properties = section_step.output_contract["properties"]["source_sections"][
        "items"
    ]["properties"]
    assert "section_title" in section_properties
    assert "section_body" in section_properties

    body_writer_step = compiled.steps[-2]
    assert body_writer_step.output_mode == OutputMode.COMPOSE_TEXT
    assert body_writer_step.input_bindings["source_refs"][0]["step_ref"] == "step_b"
    assert body_writer_step.input_bindings["source_refs"][0]["field_path"] == (
        "source_sections"
    )
    assert validate_spec(compiled).valid


def test_report_disposition_both_replaces_weak_section_text_writer() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Rapport över dokument",
            "plan_rationale": "Läs källor, skriv källavsnitt och slutrapport.",
            "steps": [
                {
                    "name": "Läs dokumenten",
                    "instructions": "Läs varje dokument och strukturera fakta.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "En post per dokument.",
                            "item_fields": [
                                {
                                    "name": "title",
                                    "field_type": "string",
                                    "description": "Titel.",
                                },
                                {
                                    "name": "summary",
                                    "field_type": "string",
                                    "description": "Sammanfattning.",
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Bygg rapportavsnitt",
                    "instructions": "Skriv ett rapportavsnitt per dokument.",
                    "output_fields": [
                        {
                            "name": "section_text",
                            "field_type": "string",
                            "description": "Färdig rapporttext för dokumentet.",
                        }
                    ],
                },
                {
                    "name": "Skriv samlad översikt",
                    "instructions": "Skriv en samlad översikt.",
                    "output_fields": [
                        {
                            "name": "overview",
                            "field_type": "string",
                            "description": "Samlad översikt.",
                        }
                    ],
                },
                {
                    "name": "Sätt ihop slutrapport",
                    "instructions": "Sätt ihop slutrapporten.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.PASS_THROUGH,
            runtime_max_files=4,
            aggregation_intent=cast(AggregationIntent, "aggregate"),
            ui_language="sv",
            report_disposition="both",
            runtime_input_fields=(
                _confirmed_runtime_field(
                    "case_id", "Ärendenummer", purpose="whole_flow"
                ),
            ),
        ),
    )

    assert [step.name for step in compiled.steps] == [
        "Läs dokumenten",
        "Bygg källavsnitt",
        "Skriv samlad översikt",
        "Sätt ihop slutrapport",
        "Rendera PDF",
    ]
    assert [step.output_mode for step in compiled.steps] == [
        OutputMode.PASS_THROUGH,
        OutputMode.PASS_THROUGH,
        OutputMode.PASS_THROUGH,
        OutputMode.COMPOSE_TEXT,
        OutputMode.RENDER_VERBATIM,
    ]
    section_writer_step = compiled.steps[1]
    assert section_writer_step.input_bindings is None
    assert section_writer_step.input_type == InputType.JSON
    assert section_writer_step.input_contract == compiled.steps[0].output_contract
    assert "case_id: {{ flow_input.case_id }}" in (
        section_writer_step.assistant_spec.instructions
    )
    assert section_writer_step.input_config is not None
    assert section_writer_step.input_config["item_map"]["enabled"] is True
    body_writer_step = compiled.steps[-2]
    assert body_writer_step.input_bindings == {
        "question": "# {{ step_c.output.structured.report_title }}",
        "source_refs": [
            {
                "step_ref": "step_b",
                "output": "structured",
                "field_path": "source_sections",
                "item_template": (
                    "## {section_title}\n\n{section_body}\n\nKälla: {source_label}"
                ),
            },
            {
                "step_ref": "step_c",
                "output": "structured",
                "field_path": "overall_overview",
                "label": "Samlad översikt",
            },
        ],
    }
    validation = validate_spec(compiled)
    assert validation.valid, validation.errors


def test_report_disposition_both_inserts_missing_source_section_map() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Dokumentöversikt i PDF",
            "plan_rationale": "Läs dokument, skriv översikt och rendera PDF.",
            "steps": [
                {
                    "name": "Läs varje dokument",
                    "instructions": "Läs varje dokument och strukturera fakta.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "En post per dokument.",
                            "item_fields": [
                                {
                                    "name": "title",
                                    "field_type": "string",
                                    "description": "Dokumentets titel.",
                                },
                                {
                                    "name": "document_type",
                                    "field_type": "string",
                                    "description": "Dokumenttyp.",
                                },
                                {
                                    "name": "category",
                                    "field_type": "string",
                                    "description": "Kategori.",
                                },
                                {
                                    "name": "summary",
                                    "field_type": "string",
                                    "description": "Kort sammanfattning.",
                                },
                                {
                                    "name": "conclusions",
                                    "field_type": "string",
                                    "description": "Slutsatser.",
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Sammanställ översikt",
                    "instructions": "Jämför dokumenten och skapa en samlad översikt.",
                    "output_fields": [
                        {
                            "name": "overview",
                            "field_type": "string",
                            "description": "Samlad översikt.",
                        },
                        {
                            "name": "overall_conclusion",
                            "field_type": "string",
                            "description": "Samlad slutsats.",
                        },
                    ],
                },
                {
                    "name": "Skriv rapporttext",
                    "instructions": "Skriv den kompletta rapporttexten för PDF-dokumentet.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.PASS_THROUGH,
            runtime_max_files=4,
            aggregation_intent=cast(AggregationIntent, "aggregate"),
            ui_language="sv",
            report_disposition="both",
            result_contract_output_fields=(
                StructuredFieldDraft(
                    name="open_questions",
                    field_type="string",
                    description="Öppna frågor som behöver följas upp.",
                ),
            ),
        ),
    )

    assert [step.name for step in compiled.steps] == [
        "Läs varje dokument",
        "Bygg källavsnitt",
        "Sammanställ översikt",
        "Skriv rapporttext",
        "Rendera PDF",
    ]
    section_step = compiled.steps[1]
    assert section_step.input_config == {"item_map": {"enabled": True, "max_items": 4}}
    section_properties = section_step.output_contract["properties"]["source_sections"][
        "items"
    ]["properties"]
    assert list(section_properties) == [
        "section_title",
        "section_body",
        "source_label",
        "source_file_id",
    ]
    assert "source_label" not in section_step.assistant_spec.instructions

    overview_step = compiled.steps[2]
    assert list(overview_step.output_contract["properties"]) == [
        "overall_conclusion",
        "report_title",
        "overall_overview",
        "open_questions",
    ]

    compose_step = compiled.steps[3]
    assert compose_step.output_mode == OutputMode.COMPOSE_TEXT
    assert compose_step.input_source == InputSource.PREVIOUS_STEP
    assert compose_step.input_bindings == {
        "question": "# {{ step_c.output.structured.report_title }}",
        "source_refs": [
            {
                "step_ref": "step_b",
                "output": "structured",
                "field_path": "source_sections",
                "item_template": (
                    "## {section_title}\n\n{section_body}\n\nKälla: {source_label}"
                ),
            },
            {
                "step_ref": "step_c",
                "output": "structured",
                "field_path": "overall_overview",
                "label": "Samlad översikt",
            },
            {
                "step_ref": "step_c",
                "output": "structured",
                "field_path": "overall_conclusion",
                "label": "Overall conclusion",
            },
            {
                "step_ref": "step_c",
                "output": "structured",
                "field_path": "open_questions",
                "label": "Open questions",
            },
        ],
    }
    assert all(
        step.input_source != InputSource.ALL_PREVIOUS_STEPS for step in compiled.steps
    )
    assert validate_spec(compiled).valid


def test_item_map_keeps_source_identity_in_contract_but_not_model_fields() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Rapport per källa",
            "plan_rationale": "Läs dokument, skriv avsnitt per källa och rendera PDF.",
            "steps": [
                {
                    "name": "Läs dokumenten",
                    "instructions": "Extrahera fakta per dokument.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "En post per dokument.",
                            "item_fields": [
                                {
                                    "name": "title",
                                    "field_type": "string",
                                    "description": "Dokumentets titel.",
                                },
                                {
                                    "name": "summary",
                                    "field_type": "string",
                                    "description": "Kort sammanfattning.",
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Bygg källavsnitt",
                    "instructions": "Skriv ett färdigt avsnitt per dokument.",
                    "output_fields": [
                        {
                            "name": "source_sections",
                            "field_type": "array",
                            "description": "Färdiga rapportavsnitt per källa.",
                            "item_fields": [
                                {
                                    "name": "section_title",
                                    "field_type": "string",
                                    "description": "Rubrik för avsnittet.",
                                },
                                {
                                    "name": "section_body",
                                    "field_type": "string",
                                    "description": "Färdig avsnittstext.",
                                },
                                {
                                    "name": "source_label",
                                    "field_type": "string",
                                    "description": "Runtimeägd källetikett.",
                                },
                                {
                                    "name": "source_file_id",
                                    "field_type": "string",
                                    "description": "Runtimeägt fil-id.",
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Sätt ihop slutrapport",
                    "instructions": "Sätt ihop rapporten.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.PASS_THROUGH,
            runtime_max_files=4,
            aggregation_intent=cast(AggregationIntent, "aggregate"),
            ui_language="sv",
            report_disposition="both",
        ),
    )

    section_step = compiled.steps[1]
    assert section_step.input_config == {"item_map": {"enabled": True, "max_items": 4}}
    assert section_step.output_contract is not None
    section_properties = section_step.output_contract["properties"]["source_sections"][
        "items"
    ]["properties"]
    assert list(section_properties) == [
        "section_title",
        "section_body",
        "source_label",
        "source_file_id",
    ]
    assert section_step.output_contract["properties"]["source_sections"]["items"][
        "required"
    ] == [
        "section_title",
        "section_body",
        "source_label",
        "source_file_id",
    ]
    instructions = section_step.assistant_spec.instructions
    assert (
        "Allowed fields for items of source_sections: section_title, section_body."
        in instructions
    )
    assert "Allowed fields for items of source_sections: source_label" not in (
        instructions
    )
    assert validate_spec(compiled).valid


def test_bare_localized_document_array_gets_source_identity_contract() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Dokumentanalys till PDF",
            "plan_rationale": "Läs dokument och skriv en PDF-rapport.",
            "steps": [
                {
                    "name": "Identifiera dokumentens innehåll",
                    "instructions": "Läs varje dokument och strukturera fakta.",
                    "output_fields": [
                        {
                            "name": "dokument",
                            "field_type": "array",
                            "description": "En post per dokument.",
                        }
                    ],
                },
                {
                    "name": "Skriv rapportinnehåll",
                    "instructions": "Skriv rapporten.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.PASS_THROUGH,
            runtime_max_files=4,
            aggregation_intent=cast(AggregationIntent, "linear"),
            ui_language="sv",
        ),
    )

    assert [step.output_type for step in compiled.steps] == [
        OutputType.JSON,
        OutputType.TEXT,
        OutputType.PDF,
    ]
    reader_step = compiled.steps[0]
    renderer_step = compiled.steps[-1]
    assert reader_step.output_contract is not None
    documents_schema = reader_step.output_contract["properties"]["documents"]
    assert documents_schema["items"]["type"] == "object"
    assert list(documents_schema["items"]["properties"]) == [
        "source_label",
        "source_file_id",
    ]
    assert documents_schema["items"]["required"] == [
        "source_label",
        "source_file_id",
    ]
    reader_instructions = reader_step.assistant_spec.instructions
    assert "körs en gång per uppladdad källa" in reader_instructions
    assert "source_label" not in reader_instructions
    assert "source_file_id" not in reader_instructions
    assert "Allowed fields for items of documents:" not in reader_instructions
    assert renderer_step.output_mode == OutputMode.RENDER_VERBATIM
    assert validate_spec(compiled).valid


def test_terminal_text_writer_fields_are_folded_into_instructions() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Dokumentrapport",
            "plan_rationale": "Extrahera dokumentfakta och skriv en rapport.",
            "steps": [
                {
                    "name": "Läs dokumentet",
                    "instructions": "Extrahera dokumentfakta.",
                    "output_fields": [
                        {
                            "name": "document_title",
                            "field_type": "string",
                            "description": "Titel från dokumentet.",
                        }
                    ],
                },
                {
                    "name": "Skriv rapport",
                    "instructions": "Skriv den slutliga rapporttexten.",
                    "output_fields": [
                        {
                            "name": "short_summary",
                            "field_type": "string",
                            "description": "Kort sammanfattning.",
                        }
                    ],
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.TEXT,
            final_output_mode=OutputMode.PASS_THROUGH,
        ),
    )

    writer_step = compiled.steps[-1]
    assert writer_step.output_type == OutputType.TEXT
    assert writer_step.output_contract is None
    assert "Kort sammanfattning" in writer_step.assistant_spec.instructions
    assert "short_summary" not in writer_step.assistant_spec.instructions
    assert "aldrig som JSON" in writer_step.assistant_spec.instructions
    assert validate_spec(compiled).valid


def test_single_source_text_report_materializes_missing_reader() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Dokumentrapport",
            "plan_rationale": "Skriv en kort rapport från dokumentet.",
            "steps": [
                {
                    "name": "Skriv rapport",
                    "instructions": "Skriv en rapport med titel och sammanfattning.",
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        outline,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.TEXT,
            final_output_mode=OutputMode.PASS_THROUGH,
            source_reader_required_fields=(
                SourceCaptureField(
                    name="document_title",
                    description="Titel från dokumentet.",
                ),
                SourceCaptureField(
                    name="short_summary",
                    description="Kort sammanfattning från dokumentet.",
                ),
            ),
            ui_language="sv",
        ),
    )

    assert [step.name for step in compiled.steps] == [
        "Extrahera källfält",
        "Skriv rapport",
    ]
    reader_step = compiled.steps[0]
    writer_step = compiled.steps[1]
    assert reader_step.input_type == InputType.DOCUMENT
    assert reader_step.output_type == OutputType.JSON
    assert reader_step.output_contract is not None
    assert sorted(reader_step.output_contract["properties"]) == [
        "document_title",
        "short_summary",
    ]
    assert writer_step.input_source == InputSource.PREVIOUS_STEP
    assert writer_step.output_type == OutputType.TEXT
    assert "Titel från dokumentet" in writer_step.assistant_spec.instructions
    assert "aldrig som JSON" in writer_step.assistant_spec.instructions
    assert "Kort sammanfattning" in writer_step.assistant_spec.instructions
    assert validate_spec(compiled).valid


@pytest.mark.parametrize(
    ("mapped_file_limit", "expected_runtime_max_files"),
    [
        (MappedFileLimit(), None),
        (
            MappedFileLimit(
                proposed_value=8,
                diagnostic="confirmation_required",
            ),
            None,
        ),
        (
            MappedFileLimit(
                proposed_value=1,
                accepted_value=1,
                provenance="authored",
            ),
            1,
        ),
    ],
    ids=["policy-unset", "unaccepted-policy", "accepted-one"],
)
def test_single_call_report_state_to_lowering_matrix(
    mapped_file_limit: MappedFileLimit,
    expected_runtime_max_files: int | None,
) -> None:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "documents"),
        "terminal_output": _slot("terminal_output", "pdf_document"),
        "pdf_generation_mode": _slot("pdf_generation_mode", "generated_pdf"),
        "document_material_scope": _slot(
            "document_material_scope", "multiple_documents_case"
        ),
        "report_disposition": _slot("report_disposition", "per_source_sections"),
    }
    state.mapped_file_limit = mapped_file_limit
    _commit_architecture(state)

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.runtime_max_files == expected_runtime_max_files
    compiled = compile_create_intent_to_spec(
        parse_create_flow_intent_arguments(
            {
                "flow_name": "Bounded report",
                "plan_rationale": "Read sources and write the committed report.",
                "steps": [
                    {
                        "name": "Read documents",
                        "instructions": "Extract one summary per source.",
                        "output_fields": [
                            {
                                "name": "documents",
                                "field_type": "array",
                                "description": "One record per source.",
                                "item_fields": [
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
                        "name": "Write report",
                        "instructions": "Write the report.",
                    },
                ],
            }
        ),
        context=context,
    )

    runtime_input = compiled.steps[0].input_config["runtime_input"]
    assert runtime_input.get("max_files") == expected_runtime_max_files
    assert runtime_input.get("execution_mode") is None
    assert compiled.steps[-2].output_mode == OutputMode.COMPOSE_TEXT
    assert validate_spec(compiled).valid


@pytest.mark.parametrize(
    "sections",
    [
        ("Résumé", "Resume", "Findings", "Recommendations"),
        ("Risk / controls", "Risk controls", "Findings", "Recommendations"),
        ("💡💡💡", "Background", "Findings", "Recommendations"),
        ("Source label", "Section title", "Section body", "Report title"),
    ],
    ids=[
        "accent-collision",
        "punctuation-collision",
        "empty-derived-key",
        "reserved-looking-labels",
    ],
)
@pytest.mark.parametrize(
    "report_disposition",
    ["per_source_sections", "synthesized_overview", "both"],
)
def test_requested_section_labels_get_lossless_collision_proof_contracts(
    sections: tuple[str, ...],
    report_disposition: ReportDisposition,
) -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Source report",
            "plan_rationale": "Extract source evidence and render the report.",
            "steps": [
                {
                    "name": "Read documents",
                    "instructions": "Extract source-grounded evidence.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "One record per source.",
                            "item_fields": [
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
                    "name": "Write report",
                    "instructions": "Write the requested report.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            report_disposition=report_disposition,
            requested_output_sections=RequestedOutputSections(
                sections=sections,
                confidence="high",
            ),
            runtime_max_files=4,
            ui_language="en",
        ),
    )
    compose = next(
        step for step in compiled.steps if step.output_mode == OutputMode.COMPOSE_TEXT
    )
    refs = source_ref_bindings(compose.input_bindings)
    for index, original_label in enumerate(sections, start=1):
        key = f"requested_section_{index}"
        assert any(
            (ref.field_path == (key,) and ref.label == original_label)
            or (
                ref.item_template is not None
                and key in item_template_field_names(ref.item_template)
                and f"{original_label}: {{{key}}}" in ref.item_template
            )
            for ref in refs
        )
    validation = validate_spec(compiled)
    assert validation.valid, validation.errors
    issue_ids = {
        issue.id
        for issue in evaluate_critic_invariants(
            build_conversation_critic_context(
                [],
                compiled,
                requested_output_sections=RequestedOutputSections(
                    sections=sections,
                    confidence="high",
                ),
            )
        )
    }
    assert "requested_output_sections_require_section_writers" not in issue_ids


@pytest.mark.parametrize(
    "report_disposition",
    ["per_source_sections", "synthesized_overview", "both"],
)
def test_requested_section_labels_with_braces_compile_for_every_disposition(
    report_disposition: ReportDisposition,
) -> None:
    requested_sections = extract_requested_output_sections(
        "Create a report with these sections:\n"
        "- Risk {qualitative}\n"
        "- Background\n"
        "- Findings\n"
        "- Recommendations"
    )
    assert requested_sections == RequestedOutputSections(
        sections=(
            "Risk {qualitative}",
            "Background",
            "Findings",
            "Recommendations",
        ),
        confidence="high",
    )
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Source report",
            "plan_rationale": "Extract source evidence and render the report.",
            "steps": [
                {
                    "name": "Read documents",
                    "instructions": "Extract source-grounded evidence.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "One record per source.",
                            "item_fields": [
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
                    "name": "Write report",
                    "instructions": "Write the requested report.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            report_disposition=report_disposition,
            requested_output_sections=requested_sections,
            runtime_max_files=4,
            ui_language="en",
        ),
    )

    compose = next(
        step for step in compiled.steps if step.output_mode == OutputMode.COMPOSE_TEXT
    )
    refs = source_ref_bindings(compose.input_bindings)
    assert any(
        ref.label == "Risk {qualitative}"
        or (
            ref.item_template is not None
            and "Risk &#123;qualitative&#125;: {requested_section_1}"
            in ref.item_template
        )
        for ref in refs
    )
    validation = validate_spec(compiled)
    assert validation.valid, validation.errors
    issue_ids = {
        issue.id
        for issue in evaluate_critic_invariants(
            build_conversation_critic_context(
                [],
                compiled,
                requested_output_sections=requested_sections,
            )
        )
    }
    assert "requested_output_sections_require_section_writers" not in issue_ids


@pytest.mark.parametrize(
    "report_disposition",
    ["per_source_sections", "synthesized_overview", "both"],
)
@pytest.mark.parametrize(
    "runtime_max_files",
    [
        None,
        1,
    ],
)
def test_single_call_report_dispositions_keep_bounded_section_ownership(
    report_disposition: ReportDisposition,
    runtime_max_files: int | None,
) -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Single-call document report",
            "plan_rationale": "Read source material before writing a report.",
            "steps": [
                {
                    "name": "Read documents",
                    "instructions": "Extract one summary for each supplied source.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "One item per supplied source.",
                            "item_fields": [
                                {
                                    "name": "summary",
                                    "field_type": "string",
                                    "description": "Source-grounded summary.",
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "Write report",
                    "instructions": "Write the requested source report.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            report_disposition=report_disposition,
            runtime_max_files=runtime_max_files,
            ui_language="en",
        ),
    )

    runtime_input = compiled.steps[0].input_config["runtime_input"]
    assert runtime_input.get("max_files") == runtime_max_files
    assert runtime_input.get("execution_mode") is None
    reader_instructions = compiled.steps[0].assistant_spec.instructions
    assert "source_label" in reader_instructions
    assert "Runtime-managed fields for items of documents" not in reader_instructions
    reader_source_label = compiled.steps[0].output_contract["properties"]["documents"][
        "items"
    ]["properties"]["source_label"]
    assert "Model-emitted" in reader_source_label["description"]
    assert "Allowed fields for items of documents: source_label, summary." in (
        reader_instructions
    )
    assert all("item_map" not in (step.input_config or {}) for step in compiled.steps)
    if report_disposition in {"per_source_sections", "both"}:
        section_step = next(
            step
            for step in compiled.steps
            if "source_sections" in (step.output_contract or {}).get("properties", {})
        )
        section_properties = section_step.output_contract["properties"][
            "source_sections"
        ]["items"]["properties"]
        assert "section_title" in section_properties
        assert "section_body" in section_properties
        assert "source_label" in section_properties
        assert "source_file_id" not in section_properties
        section_instructions = section_step.assistant_spec.instructions
        assert "copy its source_label" in section_instructions
        assert (
            "Allowed fields for items of source_sections: section_title, "
            "section_body, source_label."
        ) in section_instructions
        assert (
            "Runtime-managed fields for items of source_sections"
            not in section_instructions
        )
    assert compiled.steps[-2].output_mode == OutputMode.COMPOSE_TEXT
    validation = validate_spec(compiled)
    assert validation.valid, validation.errors


def test_mapped_reader_canonicalizes_authored_identity_fields_for_runtime() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Mapped source reader",
            "plan_rationale": "Extract one source record for each document.",
            "steps": [
                {
                    "name": "Read documents",
                    "instructions": "Extract grounded source evidence.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "One record per source.",
                            "item_fields": [
                                {
                                    "name": "source_label",
                                    "field_type": "number",
                                    "description": "Authored with the wrong type.",
                                },
                                {
                                    "name": "source_file_id",
                                    "field_type": "boolean",
                                    "description": "Authored with the wrong type.",
                                },
                                {
                                    "name": "summary",
                                    "field_type": "string",
                                    "description": "Source summary.",
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Summarize",
                    "instructions": "Summarize the source evidence.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.TEXT,
            runtime_max_files=4,
            ui_language="en",
        ),
    )

    reader = compiled.steps[0]
    item_properties = reader.output_contract["properties"]["documents"]["items"][
        "properties"
    ]
    assert item_properties["source_label"]["type"] == "string"
    assert item_properties["source_file_id"]["type"] == "string"
    runtime_steps = parse_runtime_steps(
        {
            "steps": [
                {
                    "step_id": str(uuid4()),
                    "step_order": 1,
                    "assistant_id": str(uuid4()),
                    "input_source": reader.input_source.value,
                    "input_type": reader.input_type.value,
                    "output_type": reader.output_type.value,
                    "output_mode": reader.output_mode.value,
                    "input_config": reader.input_config,
                    "output_contract": reader.output_contract,
                }
            ]
        }
    )
    assert runtime_steps[0].input_config["runtime_input"]["execution_mode"] == (
        "per_source"
    )


def test_single_call_reader_removes_authored_runtime_source_file_id() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Single-call source reader",
            "plan_rationale": "Extract source records in one call.",
            "steps": [
                {
                    "name": "Read documents",
                    "instructions": "Extract grounded source evidence.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "One record per source.",
                            "item_fields": [
                                {
                                    "name": "source_label",
                                    "field_type": "number",
                                    "description": "Authored with the wrong type.",
                                },
                                {
                                    "name": "source_file_id",
                                    "field_type": "string",
                                    "description": "Runtime-only identity.",
                                },
                                {
                                    "name": "summary",
                                    "field_type": "string",
                                    "description": "Source summary.",
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Summarize",
                    "instructions": "Summarize the source evidence.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.TEXT,
            runtime_max_files=1,
            ui_language="en",
        ),
    )

    reader = compiled.steps[0]
    item_properties = reader.output_contract["properties"]["documents"]["items"][
        "properties"
    ]
    assert item_properties["source_label"]["type"] == "string"
    assert "source_file_id" not in item_properties
    assert "source_file_id" not in reader.assistant_spec.instructions


_ACTION_FOLLOWUP_ROLES: tuple[ResultOutputFieldRole, ...] = (
    "decisions",
    "actions",
    "owners",
    "deadlines",
    "open_questions",
)


def _action_followup_contract_fields() -> tuple[StructuredFieldDraft, ...]:
    return tuple(
        StructuredFieldDraft(
            name=name,
            field_type="string",
            description=f"{name} grundade i underlaget.",
        )
        for name in ("decisions", "actions", "owners", "deadlines", "open_questions")
    )


def test_action_followup_all_text_intent_gains_a_followup_contract_step() -> None:
    # Mirrors the 2026-08-05 production failure: audio in, PDF out,
    # action_followup goal, and a model intent with only readable text steps
    # plus a render helper. Without a compiler-owned structured step the
    # critic demands a contract no repair can produce — terminal text fields
    # are folded away before completion looks.
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Mötesuppföljning",
            "plan_rationale": "Transkribera, sammanfatta och skapa PDF.",
            "steps": [
                {
                    "name": "Lättläst transkript",
                    "instructions": "Gör transkriptet lättläst med talare och stycken.",
                },
                {
                    "name": "Sammanfattning och uppföljning",
                    "instructions": "Sammanfatta mötet och lyft beslut och åtgärder.",
                },
                {
                    "name": "Skapa PDF",
                    "instructions": "Skapa PDF-dokumentet.",
                },
            ],
        }
    )

    planning_state = PlanningState.empty()
    planning_state.resolved_slots["post_processing_goal"] = _slot(
        "post_processing_goal", "action_followup"
    )
    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.AUDIO,
            final_output_type=OutputType.PDF,
            result_contract_output_fields=_action_followup_contract_fields(),
            result_contract_required_roles=_ACTION_FOLLOWUP_ROLES,
            ui_language="sv",
        ),
    )

    contract_steps = [
        step for step in compiled.steps if step.output_contract is not None
    ]
    assert contract_steps, "expected a compiler-owned follow-up contract step"
    leaf_names = set(schema_leaf_property_names(contract_steps[-1].output_contract))
    assert {
        "decisions",
        "actions",
        "owners",
        "deadlines",
        "open_questions",
    } <= leaf_names
    assert validate_spec(compiled).valid

    # The terminal writer must keep BOTH inputs: the readable narrative it
    # summarizes and the extracted follow-up object. Explicit bindings
    # replace implicit input, so losing the narrative here reproduces the
    # material-loss defect.
    extraction_step = contract_steps[-1]
    extraction_index = compiled.steps.index(extraction_step)
    narrative_step = compiled.steps[extraction_index - 1]
    writer_step = compiled.steps[extraction_index + 1]
    assert writer_step.input_bindings is not None
    bound_step_refs = {
        ref["step_ref"] for ref in writer_step.input_bindings["source_refs"]
    }
    assert {
        narrative_step.plan_step_ref,
        extraction_step.plan_step_ref,
    } <= bound_step_refs

    issues = evaluate_critic_invariants(
        build_conversation_critic_context(
            [{"role": "user", "content": "Bygg flödet för mötesuppföljning."}],
            compiled,
            planning_state=planning_state,
        )
    )
    assert "action_followup_requires_followup_fields" not in {
        issue.id for issue in issues
    }


def test_action_followup_terminal_json_step_is_completed_without_duplicates() -> None:
    # A single-step JSON outcome owned by the Builder: the compiler completes
    # the missing follow-up roles in the terminal contract, and a Swedish
    # field already covering a role must not gain a canonical duplicate.
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Uppföljningsextraktion",
            "plan_rationale": "Extrahera uppföljning.",
            "steps": [
                {
                    "name": "Extrahera uppföljning",
                    "instructions": "Extrahera uppföljningspunkter ur texten.",
                    "output_fields": [
                        {
                            "name": "beslut",
                            "field_type": "array",
                            "description": "Beslut ur underlaget.",
                        }
                    ],
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.TEXT,
            final_output_type=OutputType.JSON,
            result_contract_output_fields=_action_followup_contract_fields(),
            result_contract_required_roles=_ACTION_FOLLOWUP_ROLES,
            ui_language="sv",
        ),
    )

    terminal = compiled.steps[-1]
    assert terminal.output_contract is not None
    leaf_names = set(schema_leaf_property_names(terminal.output_contract))
    assert "beslut" in leaf_names
    assert "decisions" not in leaf_names
    assert {"actions", "owners", "deadlines", "open_questions"} <= leaf_names
    assert validate_spec(compiled).valid


def test_pinned_terminal_schema_is_never_completed_with_canonical_fields() -> None:
    # A user-owned exact schema wins: the compiler must not append canonical
    # follow-up siblings into it.
    pinned_schema = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "beslut": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["beslut"],
            "additionalProperties": False,
        },
    )
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Exakt schema",
            "plan_rationale": "Extrahera enligt schema.",
            "steps": [
                {
                    "name": "Extrahera",
                    "instructions": "Extrahera fälten enligt schemat.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.TEXT,
            final_output_type=OutputType.JSON,
            terminal_output_schema=pinned_schema,
            result_contract_output_fields=_action_followup_contract_fields(),
            result_contract_required_roles=_ACTION_FOLLOWUP_ROLES,
            ui_language="sv",
        ),
    )

    terminal = compiled.steps[-1]
    assert terminal.output_contract is not None
    assert set(terminal.output_contract["properties"]) == {"beslut"}


def test_pinned_schema_action_followup_passes_the_critic_end_to_end() -> None:
    # The user-owned exact schema wins over the follow-up role obligations:
    # the compiler must not append to it AND the critic must not demand roles
    # the model cannot add — otherwise repair loops forever on a constraint
    # it does not control.
    pinned_schema = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {
                "beslut": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["beslut"],
            "additionalProperties": False,
        },
    )
    planning_state = PlanningState.empty()
    planning_state.resolved_slots["post_processing_goal"] = _slot(
        "post_processing_goal", "action_followup"
    )
    planning_state.output_schema_evidence = build_schema_evidence(
        json_schema=pinned_schema,
        source="declared_schema",
        confidence="high",
        evidence=["user_message:exact-schema"],
    )
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Exakt uppföljningsschema",
            "plan_rationale": "Extrahera enligt schema.",
            "steps": [
                {
                    "name": "Extrahera",
                    "instructions": "Extrahera fälten enligt schemat.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.TEXT,
            final_output_type=OutputType.JSON,
            terminal_output_schema=pinned_schema,
            result_contract_output_fields=_action_followup_contract_fields(),
            result_contract_required_roles=_ACTION_FOLLOWUP_ROLES,
            ui_language="sv",
        ),
    )

    assert set(compiled.steps[-1].output_contract["properties"]) == {"beslut"}
    issues = evaluate_critic_invariants(
        build_conversation_critic_context(
            [{"role": "user", "content": "Använd exakt mitt schema."}],
            compiled,
            planning_state=planning_state,
        )
    )
    assert "action_followup_requires_followup_fields" not in {
        issue.id for issue in issues
    }


def test_report_disposition_does_not_duplicate_swedish_result_fields() -> None:
    # The document-report completion path must reuse the same role-aware
    # merge: a model-declared Swedish field already covering a role must not
    # gain a canonical English sibling in the overview contract.
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Källrapport med uppföljning",
            "plan_rationale": "Sammanställ rapport med uppföljningspunkter.",
            "steps": [
                {
                    "name": "Sammanställ rapport",
                    "instructions": "Sammanställ rapporten och uppföljningen.",
                    "output_fields": [
                        {
                            "name": "beslut",
                            "field_type": "array",
                            "description": "Beslut ur underlaget.",
                        },
                        {
                            "name": "atgarder",
                            "field_type": "array",
                            "description": "Åtgärder ur underlaget.",
                        },
                    ],
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            aggregation_intent="linear",
            report_disposition="synthesized_overview",
            result_contract_output_fields=_action_followup_contract_fields(),
            result_contract_required_roles=_ACTION_FOLLOWUP_ROLES,
            runtime_max_files=4,
            ui_language="sv",
        ),
    )

    for step in compiled.steps:
        if step.output_contract is None:
            continue
        step_names = set(schema_leaf_property_names(step.output_contract))
        assert not {"beslut", "decisions"} <= step_names, step.name
        assert not {"atgarder", "actions"} <= step_names, step.name


def test_secondary_open_questions_alone_does_not_insert_extraction_step() -> None:
    # A non-action goal (e.g. summarize) with the secondary open_questions
    # obligation contributes an open_questions result field but NO required
    # roles — assembly must not graft the action-followup extraction topology
    # (an extra model call) onto such flows.
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Mötessammanfattning",
            "plan_rationale": "Transkribera och sammanfatta.",
            "steps": [
                {
                    "name": "Lättläst transkript",
                    "instructions": "Gör transkriptet lättläst.",
                },
                {
                    "name": "Sammanfattning",
                    "instructions": "Sammanfatta mötet.",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.AUDIO,
            final_output_type=OutputType.PDF,
            result_contract_output_fields=(
                StructuredFieldDraft(
                    name="open_questions",
                    field_type="string",
                    description="Öppna frågor som behöver besvaras.",
                ),
            ),
            result_contract_required_roles=(),
            ui_language="sv",
        ),
    )

    assert all(step.output_type != OutputType.JSON for step in compiled.steps)
    assert all("Uppföljningspunkter" != step.name for step in compiled.steps)
    assert validate_spec(compiled).valid


def test_only_declared_schema_evidence_pins_the_terminal_contract() -> None:
    # Named-result evidence and inferred examples are hints, not complete
    # schemas. Only a declared schema carries pinning authority.
    declared_schema_shape = cast(
        JsonObject,
        {
            "type": "object",
            "properties": {"service_reference": {}, "applicant_channels": {}},
        },
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "documents"),
        "terminal_output": _slot("terminal_output", "structured_json"),
        "post_processing_goal": _slot(
            "post_processing_goal", "extract_key_information"
        ),
        "document_material_scope": _slot(
            "document_material_scope", "single_document_case"
        ),
        "runtime_metadata_fields": _slot(
            "runtime_metadata_fields", "no_extra_metadata"
        ),
    }
    _commit_architecture(state)
    state.named_result_evidence = [
        NamedResultEvidence(
            name=name,
            confidence="high",
            evidence=[f"quote:user_message:user-1:{name}"],
        )
        for name in ("service_reference", "applicant_channels")
    ]
    named_result_context = create_compile_context_from_planning_state(state)
    assert named_result_context is not None
    assert named_result_context.terminal_output_schema is None

    state.output_schema_evidence = build_schema_evidence(
        json_schema=declared_schema_shape,
        source="declared_schema",
        confidence="high",
        evidence=["user_message:declared"],
    )
    declared_context = create_compile_context_from_planning_state(state)
    assert declared_context is not None
    assert declared_context.terminal_output_schema == declared_schema_shape


@pytest.mark.parametrize(
    ("terminal_output", "mode_slot", "mode_value"),
    [
        ("structured_text", None, None),
        ("pdf_document", "pdf_generation_mode", "generated_pdf"),
        ("docx_document", "docx_output_mode", "generated_docx"),
    ],
)
def test_non_json_named_result_evidence_cannot_change_public_plan_shape(
    terminal_output: str,
    mode_slot: str | None,
    mode_value: str | None,
) -> None:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "text"),
        "terminal_output": _slot("terminal_output", terminal_output),
    }
    if mode_slot is not None and mode_value is not None:
        state.resolved_slots[mode_slot] = _slot(mode_slot, mode_value)
    _commit_architecture(state)
    baseline_state = state.model_copy(deep=True)
    state.named_result_evidence = [
        NamedResultEvidence(
            name="case_summary",
            confidence="high",
            evidence=["quote:user_message:user-1:case summary"],
        )
    ]
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Case summary",
            "plan_rationale": "Summarize the submitted case.",
            "steps": [
                {
                    "name": "Summarize case",
                    "instructions": "Write a clear case summary.",
                }
            ],
        }
    )
    baseline_context = create_compile_context_from_planning_state(baseline_state)
    named_context = create_compile_context_from_planning_state(state)
    assert baseline_context is not None
    assert named_context == baseline_context

    baseline_spec = compile_create_intent_to_spec(intent, context=baseline_context)
    named_spec = compile_create_intent_to_spec(intent, context=named_context)

    assert named_spec == baseline_spec
    assert state.output_schema_evidence is None
    assert state.named_result_evidence[0].model_dump() == {
        "name": "case_summary",
        "evidence": ["quote:user_message:user-1:case summary"],
        "confidence": "high",
    }
    baseline_issues = evaluate_critic_invariants(
        build_conversation_critic_context(
            [{"role": "user", "content": "Write a case summary."}],
            baseline_spec,
            planning_state=baseline_state,
        )
    )
    named_issues = evaluate_critic_invariants(
        build_conversation_critic_context(
            [{"role": "user", "content": "Write a case summary."}],
            named_spec,
            planning_state=state,
        )
    )
    assert [issue.id for issue in named_issues] == [
        issue.id for issue in baseline_issues
    ]


def test_localized_keys_are_admitted_without_a_lexicon() -> None:
    # Identity is folded, wording is the author's: Swedish keys survive
    # verbatim whether or not the user named them explicitly. The localized
    # key lexicon and its user-named exemption threading are gone (live
    # builder_error, simple_document_metadata_json 2026-08-06).
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "documents"),
        "terminal_output": _slot("terminal_output", "structured_json"),
        "post_processing_goal": _slot(
            "post_processing_goal", "extract_key_information"
        ),
        "document_material_scope": _slot(
            "document_material_scope", "single_document_case"
        ),
        "runtime_metadata_fields": _slot(
            "runtime_metadata_fields", "no_extra_metadata"
        ),
    }
    _commit_architecture(state)
    state.named_result_evidence = [
        NamedResultEvidence(
            name=name,
            confidence="high",
            evidence=[f"quote:user_message:user-1:{name}"],
        )
        for name in ("sammanfattning", "dokumenttyp")
    ]
    context = create_compile_context_from_planning_state(state)
    assert context is not None

    def intent_with_fields(names: list[str]) -> object:
        return parse_create_flow_intent_arguments(
            {
                "flow_name": "Metadata",
                "plan_rationale": "Extrahera fälten.",
                "steps": [
                    {
                        "name": "Extrahera",
                        "instructions": "Extrahera dokumentets fält.",
                        "output_fields": [
                            {
                                "name": name,
                                "field_type": "string",
                                "description": f"{name} ur dokumentet.",
                                "required": True,
                            }
                            for name in names
                        ],
                    }
                ],
            }
        )

    compiled = compile_create_intent_to_spec(
        intent_with_fields(["sammanfattning", "dokumenttyp"]),
        context=context,
    )
    contract_names = set(schema_leaf_property_names(compiled.steps[-1].output_contract))
    assert {"sammanfattning", "dokumenttyp"} <= contract_names

    # A localized key the user never named survives just the same.
    state.named_result_evidence = [
        NamedResultEvidence(
            name="dokumenttyp",
            confidence="high",
            evidence=["quote:user_message:user-1:dokumenttyp"],
        )
    ]
    unhinted_context = create_compile_context_from_planning_state(state)
    assert unhinted_context is not None
    compiled = compile_create_intent_to_spec(
        intent_with_fields(["dokumenttyp", "sammanfattning"]),
        context=unhinted_context,
    )
    contract_names = set(schema_leaf_property_names(compiled.steps[-1].output_contract))
    assert {"sammanfattning", "dokumenttyp"} <= contract_names


def _compare_json_intent(*, with_fields: bool) -> object:
    def _fields(name: str) -> list[dict[str, object]]:
        if not with_fields:
            return []
        return [
            {
                "name": name,
                "field_type": "string",
                "description": f"{name} från jämförelsen.",
                "required": True,
            }
        ]

    return parse_create_flow_intent_arguments(
        {
            "flow_name": "Jämförelse till JSON",
            "plan_rationale": "Jämför källorna och leverera maskinläsbart resultat.",
            "steps": [
                {
                    "name": "Läs källor",
                    "instructions": "Läs varje källa och extrahera jämförelsegrunden.",
                    "output_fields": _fields("comparison_basis"),
                },
                {
                    "name": "Analysera skillnader",
                    "instructions": "Analysera skillnaderna mellan källorna.",
                    "output_fields": _fields("deviations"),
                },
                {
                    "name": "Sammanställ resultat",
                    "instructions": "Sammanställ jämförelsen som strukturerat resultat.",
                },
            ],
        }
    )


def test_compare_json_terminal_compiles_with_typed_fan_in() -> None:
    # DECIDED product direction (B9(e2)): compare flows may deliver JSON.
    # The terminal consumes every retained producer through explicit
    # structured refs — the ALL_PREVIOUS_STEPS fallback is impossible here.
    compiled = compile_create_intent_to_spec(
        _compare_json_intent(with_fields=True),
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.JSON,
            aggregation_intent="compare",
            ui_language="sv",
        ),
    )

    terminal = compiled.steps[-1]
    assert terminal.output_type == OutputType.JSON
    assert terminal.input_source == InputSource.PREVIOUS_STEP
    refs = (terminal.input_bindings or {}).get("source_refs") or []
    assert {ref["step_ref"] for ref in refs} == {"step_a", "step_b"}
    assert all(ref["output"] == "structured" for ref in refs)
    assert validate_spec(compiled).valid


def test_compare_json_without_structured_fields_rejects_source_reader() -> None:
    with pytest.raises(AIBuilderArchitectureError) as excinfo:
        compile_create_intent_to_spec(
            _compare_json_intent(with_fields=False),
            context=CreateCompileContext(
                runtime_input_type=InputType.DOCUMENT,
                final_output_type=OutputType.JSON,
                aggregation_intent="compare",
                ui_language="sv",
            ),
        )
    assert (
        excinfo.value.log_context.get("failure_code")
        == "assembly_source_file_first_step_requires_json"
    )


def test_aggregate_json_terminal_still_rejects() -> None:
    with pytest.raises(AIBuilderArchitectureError) as excinfo:
        compile_create_intent_to_spec(
            _compare_json_intent(with_fields=True),
            context=CreateCompileContext(
                runtime_input_type=InputType.DOCUMENT,
                final_output_type=OutputType.JSON,
                aggregation_intent="aggregate",
                ui_language="sv",
            ),
        )
    assert (
        excinfo.value.log_context.get("failure_code")
        == "assembly_aggregate_requires_text_or_document_output"
    )
