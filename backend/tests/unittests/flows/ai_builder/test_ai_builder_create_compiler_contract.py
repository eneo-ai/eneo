from __future__ import annotations

from datetime import datetime, timezone
from typing import cast
from uuid import UUID

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
from eneo.flows.ai_builder.ai_builder_assembly import (
    try_compile_create_intent_with_assembly,
)
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    CreateCompileContext,
    compile_create_intent_to_spec,
    create_compile_context_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    FlowInputFieldIntent,
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_fields import (
    RuntimeInputFieldHint,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    build_schema_evidence,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import SourceCaptureField
from eneo.flows.ai_builder.ai_builder_validator import validate_spec
from eneo.flows.ai_builder.pattern_registry import (
    EXTRACT_TEMPLATE_VARIABLES_STEP,
    FLOW_INPUT_AUDIO_TRANSCRIPTION,
    FLOW_INPUT_DOCUMENT_UPLOAD,
    TEMPLATE_FILL_DOCX_STEP,
    TERMINAL_ARTIFACT_STEP,
)
from eneo.flows.ai_builder.planning_state import (
    AggregationIntent,
    ExampleOutputCitation,
    ExampleOutputConstraintEvidence,
    ExampleOutputSchemaInferenceOutcome,
    ExampleOutputSourceCoverage,
    FileRoleEvidence,
    MappedFileLimit,
    PlanningSignal,
    PlanningState,
    ResolvedSlot,
    SchemaResolution,
)
from eneo.flows.flow_authoring_spec import (
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from eneo.flows.input_binding_contract_rules import effective_question_binding
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


def test_compile_context_ignores_non_commit_grade_runtime_metadata() -> None:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", "documents"),
        "terminal_output": _slot("terminal_output", "structured_text"),
        "document_material_scope": _slot(
            "document_material_scope",
            "single_document_case",
        ),
    }
    _commit_architecture(state)
    state.resolved_slots["runtime_metadata_fields"] = ResolvedSlot(
        name="runtime_metadata_fields",
        value="no_extra_metadata",
        source="model",
        confidence="medium",
        evidence=["quote:user_message:example:no extra fields were mentioned"],
    )

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.runtime_metadata_state is None


def test_policy_default_does_not_override_confirmed_runtime_fields() -> None:
    state = PlanningState.empty()
    state.resolved_slots["runtime_metadata_fields"] = ResolvedSlot(
        name="runtime_metadata_fields",
        value="no_extra_metadata",
        source="policy_default",
        confidence="high",
    )
    state.input_fields = [
        FlowInputFieldIntent(
            variable_name="case_type",
            label="Case type",
            provenance="user_confirmed",
        )
    ]
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
                    "uses_form_fields": ["case_type"],
                    "output_type": "text",
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(intent, context=context)

    assert [field.name for field in compiled.form_fields or ()] == ["case_type"]
    assert "{{ flow_input.case_type }}" in _question(compiled.steps[0].input_bindings)


def test_confirmed_runtime_field_set_rejects_model_proposed_addition() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Case routing",
            "plan_rationale": "Route the case with its runtime fields.",
            "input_fields": [
                {"name": "case_type", "label": "Case type"},
                {"name": "tone", "label": "Tone"},
            ],
            "steps": [
                {
                    "name": "Route case",
                    "instructions": "Route the case using its type and tone.",
                    "uses_form_fields": ["case_type", "tone"],
                    "output_type": "text",
                }
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            intent,
            context=CreateCompileContext(
                runtime_metadata_state="detailed_runtime_metadata",
                runtime_input_field_hints=(
                    RuntimeInputFieldHint(
                        variable_name="case_type",
                        label="Case type",
                        provenance="user_confirmed",
                    ),
                ),
            ),
        )

    assert exc_info.value.log_context["failure_code"] == (
        "unconfirmed_runtime_form_fields"
    )
    assert exc_info.value.log_context["field_names"] == "tone"


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
                    "output_type": "json",
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
                    "output_type": "json",
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
            "input_fields": [
                {
                    "variable_name": "case_type",
                    "label": "Case type",
                    "field_type": "text",
                    "required": True,
                }
            ],
            "steps": [
                {
                    "name": "Normalize case",
                    "instructions": "Validate the case for the selected case type.",
                    "output_type": "json",
                    "uses_form_fields": ["case_type"],
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
            ),
        )

    assert exc_info.value.log_context["failure_code"] == (
        "flow_input_schema_composite_bindings_unsupported"
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
    assert context.terminal_output_schema == schema
    assert "required" not in context.terminal_output_schema
    assert "additionalProperties" not in context.terminal_output_schema


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
            "input_fields": [
                {
                    "variable_name": "tone",
                    "label": "Tone",
                    "field_type": "text",
                    "required": True,
                }
            ],
            "steps": [
                {
                    "name": "Write answer",
                    "instructions": "Write the answer in the requested tone.",
                    "output_type": "text",
                    "uses_form_fields": ["tone"],
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(intent)

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
                    "output_type": "text",
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
                    "output_type": "text",
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
                    "output_type": "text",
                },
                {
                    "name": "Skapa DOCX",
                    "instructions": "Skapa DOCX-dokumentet.",
                    "output_type": "docx",
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


def test_missing_document_report_compose_topology_is_typed_architecture_failure() -> (
    None
):
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Broken report",
            "plan_rationale": "No source-section topology can be derived.",
            "steps": [
                {
                    "name": "Write report body",
                    "instructions": "Write the report body.",
                    "output_type": "text",
                }
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            intent,
            context=CreateCompileContext(
                runtime_input_type=InputType.TEXT,
                final_output_type=OutputType.PDF,
                final_output_mode=OutputMode.RENDER_VERBATIM,
                aggregation_intent=cast(AggregationIntent, "aggregate"),
                report_disposition="both",
            ),
        )

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.log_context["failure_code"] == (
        "assembly_document_report_compose_topology_missing"
    )
    assert "deterministic compose_text body writer" in exc_info.value.detail


def test_assembly_fails_closed_when_document_report_compose_topology_is_missing() -> (
    None
):
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Broken report",
            "plan_rationale": "No source-section topology can be derived.",
            "steps": [
                {
                    "name": "Write report body",
                    "instructions": "Write the report body.",
                    "output_type": "text",
                }
            ],
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        try_compile_create_intent_with_assembly(
            intent,
            runtime_input_type=InputType.TEXT,
            final_output_type=OutputType.PDF,
            final_output_mode=OutputMode.RENDER_VERBATIM,
            form_fields=(),
            pattern_ids=(),
            chain_steps=(),
            aggregation_intent=cast(AggregationIntent, "aggregate"),
            terminal_output_schema=None,
            source_reader_required_fields=(),
            result_contract_output_fields=(),
            report_disposition="both",
            runtime_required=True,
            runtime_max_files=None,
            ui_language="sv",
        )

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.log_context["failure_code"] == (
        "assembly_document_report_compose_topology_missing"
    )


def test_compiler_strips_stale_previous_field_refs_and_uses_whole_object_underlag() -> (
    None
):
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Case summary",
            "flow_description": "Extract facts and write a short summary.",
            "plan_rationale": "Extract structured facts before writing.",
            "input_fields": [
                {
                    "variable_name": "case_id",
                    "label": "Case ID",
                    "field_type": "text",
                    "required": True,
                }
            ],
            "steps": [
                {
                    "name": "Extract facts",
                    "instructions": "Extract the relevant facts.",
                    "output_type": "json",
                    "uses_form_fields": ["case_id"],
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
                    "output_type": "text",
                    "uses_previous_fields": [
                        {
                            "from_step": 1,
                            "field_path": "summary",
                            "label": "Summary",
                        }
                    ],
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(intent)

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
                    "output_type": "json",
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
                    "output_type": "text",
                    "uses_previous_fields": [
                        {
                            "from_step": 1,
                            "field_path": "summary",
                            "label": "Summary",
                        },
                        {
                            "from_step": 1,
                            "field_path": "details",
                            "label": "Details",
                        },
                    ],
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
                    "output_type": "json",
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
                    "output_type": "text",
                },
                {
                    "name": "Write findings",
                    "instructions": "Write the findings section.",
                    "output_type": "text",
                },
                {
                    "name": "Write recommendations",
                    "instructions": "Write the recommendations section.",
                    "output_type": "text",
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
                    "output_type": "json",
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
                    "output_type": "json",
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
                    "output_type": "text",
                },
                {
                    "name": "Write recommendations",
                    "instructions": "Write the recommendations section.",
                    "output_type": "text",
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
                    "output_type": "json",
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
                    "output_type": "json",
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
                    "output_type": "text",
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
                    "output_type": "text",
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
                    "output_type": "json",
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
                    "output_type": "json",
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
                    "output_type": "text",
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


def test_compiler_uses_server_runtime_hints_as_form_field_owner() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Bygglovsgranskning",
            "flow_description": "Jämför en ansökan mot angiven checklista.",
            "plan_rationale": "Läs ansökan, jämför mot regeln och skriv rapport.",
            "input_fields": [
                {
                    "variable_name": "checklista",
                    "label": "Model checklist label",
                    "field_type": "text",
                    "required": True,
                },
                {
                    "variable_name": "regel",
                    "label": "Model rule label",
                    "field_type": "text",
                    "required": True,
                },
            ],
            "steps": [
                {
                    "name": "Läs ansökan",
                    "instructions": "Extrahera fakta ur ansökan.",
                    "output_type": "json",
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
                    "output_type": "json",
                    "uses_form_fields": [
                        "checklista",
                        "regel",
                    ],
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
                    "output_type": "text",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.TEXT,
            runtime_metadata_state="detailed_runtime_metadata",
            runtime_input_field_hints=(
                RuntimeInputFieldHint(
                    "checklista",
                    "checklista",
                    provenance="user_confirmed",
                ),
                RuntimeInputFieldHint(
                    "regel",
                    "regel",
                    provenance="user_confirmed",
                ),
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
    assert "flow_input.checklista" not in repr(compiled.steps[-1].input_bindings)
    assert "flow_input.regel" not in repr(compiled.steps[-1].input_bindings)
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
                    "output_type": "text",
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
                    "output_type": "json",
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
                    "output_type": "text",
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


def test_assembly_drops_source_contract_shadow_form_fields_before_lowering() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Document case summary",
            "flow_description": "Extract the case id and write a summary.",
            "plan_rationale": "The source reader owns the case id contract.",
            "input_fields": [
                {
                    "variable_name": "manual_case_id",
                    "label": "Manual case id",
                    "field_type": "text",
                    "required": True,
                },
                {
                    "variable_name": "report_title",
                    "label": "Report title",
                    "field_type": "text",
                    "required": False,
                },
                {
                    "variable_name": "document_category_hint",
                    "label": "Document category hint",
                    "field_type": "text",
                    "required": False,
                },
            ],
            "steps": [
                {
                    "name": "Extract source facts",
                    "instructions": "Extract source facts from the document.",
                    "output_type": "json",
                    "uses_form_fields": [
                        "manual_case_id",
                        "report_title",
                        "document_category_hint",
                    ],
                    "output_fields": [
                        {
                            "name": "case_id",
                            "field_type": "string",
                            "description": "Case id found in the source.",
                        },
                        {
                            "name": "title",
                            "field_type": "string",
                            "description": "Title found in the source.",
                        },
                        {
                            "name": "category",
                            "field_type": "string",
                            "description": "Category found in the source.",
                        },
                    ],
                },
                {
                    "name": "Write case summary",
                    "instructions": "Write the final case summary.",
                    "output_type": "text",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.TEXT,
        ),
    )

    reader_step = compiled.steps[0]
    assert compiled.form_fields is None
    assert reader_step.input_source == InputSource.FLOW_INPUT
    assert reader_step.input_type == InputType.DOCUMENT
    assert reader_step.output_type == OutputType.JSON
    assert "manual_case_id" not in repr(reader_step.input_bindings)
    assert "report_title" not in repr(reader_step.input_bindings)
    assert "document_category_hint" not in repr(reader_step.input_bindings)
    assert validate_spec(compiled).valid


def test_assembly_rejects_confirmed_source_contract_shadow_form_field() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Document case summary",
            "plan_rationale": "The source reader owns the case id contract.",
            "input_fields": [
                {
                    "variable_name": "case_id",
                    "label": "Case id",
                }
            ],
            "steps": [
                {
                    "name": "Extract source facts",
                    "instructions": "Extract the case id from the document.",
                    "uses_form_fields": ["case_id"],
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
                    "output_type": "text",
                },
            ],
        }
    )
    intent = intent.model_copy(
        update={
            "input_fields": [
                intent.input_fields[0].model_copy(
                    update={"provenance": "user_confirmed"}
                )
            ]
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            intent,
            context=CreateCompileContext(runtime_input_type=InputType.DOCUMENT),
        )

    assert exc_info.value.log_context["failure_code"] == (
        "confirmed_form_field_incompatible"
    )
    assert exc_info.value.log_context["field_names"] == "case_id"


def test_inferred_primary_input_shadow_drop_emits_typed_diagnostic() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Audio summary",
            "plan_rationale": "Transcribe the uploaded audio.",
            "steps": [
                {
                    "name": "Summarize audio",
                    "instructions": "Summarize the audio.",
                }
            ],
        }
    )
    diagnostics = []

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.AUDIO,
            runtime_metadata_state="detailed_runtime_metadata",
            runtime_input_field_hints=(
                RuntimeInputFieldHint(
                    "audio",
                    "Audio",
                    provenance="runtime_inferred",
                ),
            ),
        ),
        field_diagnostics=diagnostics,
    )

    assert compiled.form_fields is None
    assert [(item.code, item.field_provenance) for item in diagnostics] == [
        ("primary_input_shadow_form_field_dropped", "runtime_inferred")
    ]


def test_assembly_places_explicit_server_owned_runtime_field_consumers() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Bygglovsrapport",
            "flow_description": "Läser ansökan och skriver en handläggarrapport.",
            "plan_rationale": "Dokumentet läses först och rapporten skrivs sist.",
            "steps": [
                {
                    "name": "Läs ansökan",
                    "instructions": "Extrahera uppgifter från ansökan.",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Kort sammanfattning.",
                        },
                        {
                            "name": "missing_information",
                            "field_type": "string",
                            "description": "Saknade uppgifter.",
                        },
                    ],
                },
                {
                    "name": "Skriv handläggarrapport",
                    "instructions": "Skriv en kort handläggarrapport.",
                    "uses_form_fields": [
                        "arendenummer",
                        "kommun",
                        "handlaggare",
                        "sista_svarsdatum",
                    ],
                    "output_type": "text",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.TEXT,
            runtime_metadata_state="detailed_runtime_metadata",
            runtime_input_field_hints=(
                RuntimeInputFieldHint("arendenummer", "ärendenummer", required=True),
                RuntimeInputFieldHint("kommun", "kommun", required=True),
                RuntimeInputFieldHint("handlaggare", "handläggare", required=True),
                RuntimeInputFieldHint("sista_svarsdatum", "sista svarsdatum"),
            ),
        ),
    )

    assert compiled.form_fields is not None
    assert [field.name for field in compiled.form_fields] == [
        "arendenummer",
        "kommun",
        "handlaggare",
        "sista_svarsdatum",
    ]
    report_step = compiled.steps[-1]
    question = _question(report_step.input_bindings)
    assert "{{ step_a.output.structured }}" in question
    assert "arendenummer: {{ flow_input.arendenummer }}" in question
    assert "kommun: {{ flow_input.kommun }}" in question
    assert "handlaggare: {{ flow_input.handlaggare }}" in question
    assert "sista_svarsdatum: {{ flow_input.sista_svarsdatum }}" in question
    assert validate_spec(compiled).valid


def test_confirmed_field_definition_overrides_model_redeclaration() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Case routing",
            "plan_rationale": "Route the case using its confirmed type.",
            "input_fields": [
                {
                    "variable_name": "case_type",
                    "label": "Model label",
                    "field_type": "text",
                    "required": False,
                }
            ],
            "steps": [
                {
                    "name": "Route case",
                    "instructions": "Route the case using its type.",
                    "uses_form_fields": ["case_type"],
                    "output_type": "text",
                }
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_metadata_state="detailed_runtime_metadata",
            runtime_input_field_hints=(
                RuntimeInputFieldHint(
                    "case_type",
                    "Confirmed case type",
                    field_type="select",
                    required=True,
                    options=("permit", "complaint"),
                    provenance="user_confirmed",
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
                    "output_type": "json",
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
                    "output_type": "json",
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
                    "output_type": "text",
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


def test_aggregate_document_body_keeps_fan_in_when_prior_contract_is_missing() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Aggregate report",
            "flow_description": "Extract, analyze, and render a PDF report.",
            "plan_rationale": "The body writer aggregates mixed prior work.",
            "steps": [
                {
                    "name": "Extract source facts",
                    "instructions": "Extract source facts without a stable schema.",
                    "output_type": "json",
                },
                {
                    "name": "Analyze facts",
                    "instructions": "Analyze the extracted facts.",
                    "output_type": "json",
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
                    "output_type": "text",
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
    assert body_step.input_source == InputSource.ALL_PREVIOUS_STEPS
    assert body_step.input_bindings is None
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
                    "output_type": "json",
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
                    "output_type": "text",
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
                    "output_type": "json",
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
                    "output_type": "json",
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
                    "output_type": "text",
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
                    "output_type": "json",
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
                    "output_type": "text",
                    "uses_previous_fields": [
                        {
                            "from_step": 1,
                            "field_path": "summary",
                            "label": "Summary",
                        }
                    ],
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
        FlowInputFieldIntent(
            variable_name="arendenummer",
            label="ärendenummer",
            provenance="user_confirmed",
        ),
        FlowInputFieldIntent(
            variable_name="handlaggare",
            label="handläggare",
            provenance="user_confirmed",
        ),
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
                    "uses_form_fields": ["arendenummer", "handlaggare"],
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "sakuppgifter",
                            "field_type": "string",
                            "description": "Verifierade sakuppgifter ur ljudet.",
                        }
                    ],
                    "review_mode": "edit",
                },
                {
                    "name": "Skriv rapporten",
                    "instructions": "Skriv en tydlig rapport från sakuppgifterna.",
                    "uses_form_fields": ["arendenummer", "handlaggare"],
                    "output_type": "text",
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
                    "output_type": "text",
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


def test_compiler_uses_assembly_path_for_docx_template_fill() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Template report",
            "flow_description": "Fill a DOCX template from source documents.",
            "plan_rationale": "Extract source facts, prepare content, fill template.",
            "input_fields": [
                {
                    "variable_name": "case_id",
                    "label": "Case ID",
                    "field_type": "text",
                    "required": True,
                }
            ],
            "steps": [
                {
                    "name": "Prepare template content",
                    "instructions": "Prepare the content for the DOCX template.",
                    "output_type": "text",
                    "uses_form_fields": ["case_id"],
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
            runtime_max_files=2,
        ),
    )

    assert len(compiled.steps) == 3
    reader_step = compiled.steps[0]
    content_step = compiled.steps[1]
    template_step = compiled.steps[2]
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
    assert content_step.input_source == InputSource.PREVIOUS_STEP
    assert content_step.input_type == InputType.TEXT
    assert content_step.output_type == OutputType.TEXT
    question = _question(content_step.input_bindings)
    assert "{{ step_a.output.structured }}" in question
    assert "case_id: {{ flow_input.case_id }}" in question
    assert template_step.input_source == InputSource.PREVIOUS_STEP
    assert template_step.input_type == InputType.TEXT
    assert template_step.output_type == OutputType.DOCX
    assert template_step.output_mode == OutputMode.TEMPLATE_FILL
    assert template_step.input_bindings is None
    assert validate_spec(compiled).valid


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
    state.input_fields = [
        FlowInputFieldIntent(
            variable_name="arendenummer",
            label="ärendenummer",
            provenance="user_confirmed",
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
                    "uses_form_fields": ["arendenummer"],
                    "output_type": "text",
                    "review_mode": "view",
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
    assert "flow_input.arendenummer" not in repr(template_step.input_bindings)
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
                    "uses_form_fields": ["kundnamn", "case_id"],
                    "output_type": "text",
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
        ),
    )

    assert compiled.form_fields is not None
    assert [field.name for field in compiled.form_fields] == ["kundnamn", "case_id"]
    content_step = compiled.steps[1]
    question = _question(content_step.input_bindings)
    assert "kundnamn: {{ flow_input.kundnamn }}" in question
    assert "case_id: {{ flow_input.case_id }}" in question
    assert "datum:" not in question
    assert "step_a.output.summary" not in question
    assert "text:" not in question
    assert validate_spec(compiled).valid


def test_compiler_lowers_runtime_inputs_and_derived_whole_object_underlag() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Dokumentanalys",
            "plan_rationale": "Extrahera risker och skriv slutrapport.",
            "input_fields": [
                {
                    "variable_name": "referensnummer",
                    "label": "Referensnummer",
                    "field_type": "text",
                    "required": True,
                }
            ],
            "steps": [
                {
                    "name": "Extrahera risker",
                    "instructions": "Extrahera risker och rekommendationer.",
                    "output_type": "json",
                    "uses_form_fields": ["referensnummer"],
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
                    "output_type": "text",
                    "uses_previous_fields": [
                        {
                            "from_step": 1,
                            "field_path": "summary",
                            "label": "Sammanfattning",
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
            runtime_max_files=5,
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
                    "output_type": "json",
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
                    "output_type": "json",
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
                    "output_type": "text",
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
    ("helper_output_type", "helper_instructions"),
    [
        (
            "text",
            "Omvandla den färdiga rapporttexten till en professionell PDF "
            "med tydlig struktur och läsbar layout.",
        ),
        ("pdf", "Skapa slutrapporten från den färdiga rapporttexten."),
    ],
)
def test_document_artifact_drops_model_authored_pdf_render_helper(
    helper_output_type: str,
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
                    "output_type": "json",
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
                    "output_type": "text",
                },
                {
                    "name": "Skapa PDF-rapport",
                    "instructions": helper_instructions,
                    "output_type": helper_output_type,
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
                    "output_type": "json",
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
                    "output_type": "text",
                },
                {
                    "name": "Skapa PDF-rapport",
                    "instructions": "Skapa slutrapporten som PDF.",
                    "output_type": "pdf",
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
    assert "author_or_source" in body_step.assistant_spec.instructions
    assert "conclusions" in body_step.assistant_spec.instructions
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
                    "output_type": "json",
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
                    "output_type": "text",
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
        "date_or_year",
        "author_or_sender",
        "summary",
    ]
    assert "sammanfattning" not in item_properties
    assert "documents" not in item_properties
    reader_instructions = reader_step.assistant_spec.instructions
    assert "körs en gång per uppladdad källa" in reader_instructions
    assert "source_label" not in reader_instructions
    assert "source_file_id" not in reader_instructions
    assert (
        "Allowed fields for items of documents: title, date_or_year, "
        "author_or_sender, summary."
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
                    "output_type": "json",
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
                    "output_type": "json",
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
                    "output_type": "json",
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
                    "uses_form_fields": ["case_number"],
                    "output_type": "text",
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
            runtime_metadata_state="detailed_runtime_metadata",
            runtime_input_field_hints=(
                RuntimeInputFieldHint(
                    "case_number",
                    "Case number",
                    provenance="user_confirmed",
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

    body_writer_step = compiled.steps[3]
    assert body_writer_step.input_source == InputSource.PREVIOUS_STEP
    assert body_writer_step.output_mode == OutputMode.COMPOSE_TEXT
    assert body_writer_step.input_bindings is not None
    assert "{{ flow_input.case_number }}" in _question(body_writer_step.input_bindings)
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
    assert validate_spec(compiled).valid


def test_report_disposition_both_ignores_source_section_name_without_shape() -> None:
    outline = parse_create_flow_intent_arguments(
        {
            "flow_name": "Rapport över dokument",
            "plan_rationale": "Läs källor, skriv fria källtexter och slutrapport.",
            "steps": [
                {
                    "name": "Läs dokumenten",
                    "instructions": "Läs varje dokument och strukturera fakta.",
                    "output_type": "json",
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
                    "output_type": "json",
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
                    "output_type": "text",
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
            "input_fields": [
                {
                    "name": "case_id",
                    "label": "Ärendenummer",
                    "type": "text",
                }
            ],
            "steps": [
                {
                    "name": "Läs dokumenten",
                    "instructions": "Läs varje dokument och strukturera fakta.",
                    "output_type": "json",
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
                    "uses_form_fields": ["case_id"],
                    "output_type": "json",
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
                    "output_type": "json",
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
                    "output_type": "text",
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
                    "output_type": "json",
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
                    "output_type": "json",
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
                    "output_type": "text",
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
        "report_title",
        "overall_overview",
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
                    "output_type": "json",
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
                    "output_type": "json",
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
                    "output_type": "text",
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
                    "output_type": "json",
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
                    "output_type": "text",
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
                    "output_type": "json",
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
                    "output_type": "text",
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
    assert "short_summary" in writer_step.assistant_spec.instructions
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
                    "output_type": "text",
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
        "summary",
        "title",
    ]
    assert writer_step.input_source == InputSource.PREVIOUS_STEP
    assert writer_step.output_type == OutputType.TEXT
    assert "title" in writer_step.assistant_spec.instructions
    assert "summary" in writer_step.assistant_spec.instructions
    assert validate_spec(compiled).valid


def test_compile_context_uses_only_accepted_mapped_file_limit() -> None:
    state = PlanningState.empty()
    state.mapped_file_limit = MappedFileLimit(
        proposed_value=8,
        accepted_value=3,
        provenance="authored",
    )

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.runtime_max_files == 3


def test_compile_context_does_not_use_unaccepted_policy_proposal() -> None:
    state = PlanningState.empty()
    state.mapped_file_limit = MappedFileLimit(
        proposed_value=8,
        diagnostic="confirmation_required",
    )

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.runtime_max_files is None


def test_runtime_max_files_none_keeps_document_reader_single_call() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Single-call document reader",
            "plan_rationale": "Read source material before writing a summary.",
            "steps": [
                {
                    "name": "Read documents",
                    "instructions": "Extract one summary from the supplied material.",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "The supplied source material.",
                        }
                    ],
                },
                {
                    "name": "Write summary",
                    "instructions": "Write one combined summary.",
                    "output_type": "text",
                },
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            runtime_max_files=None,
        ),
    )

    runtime_input = compiled.steps[0].input_config["runtime_input"]
    assert runtime_input.get("execution_mode") is None
    assert validate_spec(compiled).valid
