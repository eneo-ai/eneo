from __future__ import annotations

import pytest

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
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    CreateFlowIntent,
    FlowInputFieldIntent,
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_fields import (
    RuntimeInputFieldHint,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import SourceCaptureField
from eneo.flows.ai_builder.planning_state import (
    ConfirmedRuntimeMetadataField,
    PlanningState,
    RuntimeMetadataFieldPurpose,
)
from eneo.flows.flow_authoring_spec import InputType, OutputMode, OutputType
from eneo.flows.input_binding_contract_rules import effective_question_binding


def _runtime_field(
    name: str,
    purpose: RuntimeMetadataFieldPurpose,
) -> ConfirmedRuntimeMetadataField:
    return ConfirmedRuntimeMetadataField(
        value=FlowInputFieldIntent(
            variable_name=name,
            label=name.replace("_", " ").title(),
            provenance="user_confirmed",
        ),
        purpose=purpose,
        structured_answer_message_id="message-1",
    )


def _two_step_intent() -> CreateFlowIntent:
    return parse_create_flow_intent_arguments(
        {
            "flow_name": "Case response",
            "plan_rationale": "Classify the case and write a response.",
            "steps": [
                {
                    "name": "Classify case",
                    "instructions": "Classify the submitted case.",
                    "output_fields": [
                        {
                            "name": "category",
                            "field_type": "string",
                            "description": "Case category.",
                        }
                    ],
                },
                {
                    "name": "Write response",
                    "instructions": "Write the final response.",
                },
            ],
        }
    )


def _question(step: object) -> str:
    input_bindings = getattr(step, "input_bindings")
    question = effective_question_binding(input_bindings)
    return "" if question is None else question


def test_compile_context_projects_typed_runtime_field_records() -> None:
    state = PlanningState.empty()
    record = _runtime_field("audience", "whole_flow")
    state.input_fields = [record]

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.runtime_input_fields == (record,)
    assert context.runtime_input_field_hints[0].variable_name == "audience"


@pytest.mark.parametrize(
    ("purpose", "expected_step_indexes"),
    [
        ("interpret_input", (0,)),
        ("shape_result", (1,)),
        ("whole_flow", (0, 1)),
    ],
)
def test_runtime_field_purpose_places_on_final_semantic_topology(
    purpose: RuntimeMetadataFieldPurpose,
    expected_step_indexes: tuple[int, ...],
) -> None:
    compiled = compile_create_intent_to_spec(
        _two_step_intent(),
        context=CreateCompileContext(
            runtime_input_fields=(_runtime_field("audience", purpose),),
        ),
    )

    for index, step in enumerate(compiled.steps):
        reference_count = _question(step).count("{{ flow_input.audience }}")
        assert reference_count == (1 if index in expected_step_indexes else 0)


@pytest.mark.parametrize(
    ("purpose", "expected_references"),
    [
        ("interpret_input", [0, 1, 0, 1]),
        ("shape_result", [0, 0, 0, 1]),
        ("whole_flow", [0, 1, 1, 1]),
    ],
)
def test_template_overlap_uses_exact_purpose_truth_table(
    purpose: RuntimeMetadataFieldPurpose,
    expected_references: list[int],
) -> None:
    compiled = compile_create_intent_to_spec(
        _two_step_intent(),
        context=CreateCompileContext(
            runtime_input_type=InputType.DOCUMENT,
            final_output_type=OutputType.DOCX,
            final_output_mode=OutputMode.TEMPLATE_FILL,
            pattern_ids=("document_to_docx_template",),
            pattern_chain_steps=(
                "flow_input_document_upload",
                "extract_template_variables_step",
                "prepare_template_content_step",
                "template_fill_docx_step",
            ),
            selected_template_count=1,
            selected_template_placeholders=("audience",),
            runtime_input_fields=(_runtime_field("audience", purpose),),
            template_placeholder_field_hints=(
                RuntimeInputFieldHint(
                    variable_name="audience",
                    label="Audience",
                    provenance="template_derived",
                ),
            ),
        ),
    )

    references = [
        _question(step).count("{{ flow_input.audience }}") for step in compiled.steps
    ]
    assert references == expected_references
    assert compiled.steps[-1].output_config == {
        "bindings": {"audience": "{{ flow_input.audience }}"}
    }


def test_template_only_field_without_template_target_is_typed_unsupported() -> None:
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            _two_step_intent(),
            context=CreateCompileContext(
                template_placeholder_field_hints=(
                    RuntimeInputFieldHint(
                        variable_name="audience",
                        label="Audience",
                        provenance="template_derived",
                    ),
                ),
            ),
        )

    assert exc_info.value.log_context["reason"] == "form_field_no_legal_target"


def test_whole_flow_excludes_terminal_fan_in_target() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Compare notes",
            "plan_rationale": "Prepare two notes and combine them.",
            "steps": [
                {"name": "First note", "instructions": "Write the first note."},
                {"name": "Second note", "instructions": "Write the second note."},
                {"name": "Combine notes", "instructions": "Combine both notes."},
            ],
        }
    )

    compiled = compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            aggregation_intent="aggregate",
            runtime_input_fields=(_runtime_field("audience", "whole_flow"),),
        ),
    )

    references = [
        _question(step).count("{{ flow_input.audience }}") for step in compiled.steps
    ]
    assert references == [1, 1, 0]


def test_document_reader_split_and_renderer_are_not_semantic_targets() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Case report",
            "plan_rationale": "Write a report from the uploaded document.",
            "steps": [
                {
                    "name": "Write report",
                    "instructions": "Write the final report from the source.",
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
            source_reader_required_fields=(
                SourceCaptureField(name="summary", description="Source summary."),
            ),
            runtime_input_fields=(_runtime_field("audience", "interpret_input"),),
        ),
    )

    references = [
        _question(step).count("{{ flow_input.audience }}") for step in compiled.steps
    ]
    assert references == [0, 1, 0]


def test_pure_transcription_has_no_legal_semantic_target() -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Meeting transcript",
            "plan_rationale": "Transcribe the uploaded recording.",
            "steps": [
                {
                    "name": "Transcribe meeting",
                    "instructions": "Transcribe the uploaded recording.",
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
                pattern_ids=("audio_transcription",),
                post_processing_goal="stop_after_primary_operation",
                runtime_input_fields=(_runtime_field("audience", "interpret_input"),),
            ),
        )

    assert exc_info.value.log_context["reason"] == (
        "form_field_required_semantic_target_missing"
    )
