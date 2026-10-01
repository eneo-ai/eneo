"""Create binds a confirmed run-form field into every step that declares it reads it.

The oracle is what the compiled flow hands each step at runtime: the declared
consumer's resolved input carries the run's value next to the material it reads
from its predecessor, and a different run value changes it.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_authoring_projection import question_form_reads
from eneo.flows.ai_builder.ai_builder_create_compile_context import (
    CreateCompileContext,
)
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    compile_create_intent_to_spec,
)
from eneo.flows.ai_builder.ai_builder_edit_compiler import compile_edit_proposal
from eneo.flows.ai_builder.ai_builder_new_step_models import PreviousFieldRef
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    AssistantSpecPatch,
    CreateFlowIntent,
    FlowInputFieldIntent,
    ModifyExistingStep,
    OrderedEditProposal,
    SemanticStepIntent,
    build_create_flow_tool_schema,
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_requirements import (
    ConfirmedRuntimeInputRequirement,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import SourceCaptureField
from eneo.flows.ai_builder.ai_builder_tools import (
    ProposalToolArgumentsError,
    build_native_strict_tool_schema,
    validate_propose_flow_tool_arguments,
)
from eneo.flows.ai_builder.ai_builder_validator import validate_spec
from eneo.flows.ai_builder.planning_state import (
    ConfirmedRuntimeMetadataField,
    RuntimeMetadataFieldPurpose,
)
from eneo.flows.application.flow_draft_materialization import (
    compile_flow_draft_changeset,
)
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshot
from eneo.flows.domain.flow import FlowRun, FlowStep, FlowStepResult
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.input_binding_contract_rules import effective_question_binding
from eneo.flows.runtime.step_input_resolution import resolve_step_input_binding
from eneo.flows.variable_resolver import FlowVariableResolver
from tests.unittests.flows.source_ref_runtime_test_support import completed_result

_READ = "{{ flow_input.hyra }}"


def _runtime_field(
    name: str, purpose: RuntimeMetadataFieldPurpose = "interpret_input"
) -> ConfirmedRuntimeMetadataField:
    return ConfirmedRuntimeMetadataField(
        value=FlowInputFieldIntent(
            variable_name=name,
            label=name.title(),
            field_type="number",
            provenance="user_confirmed",
        ),
        purpose=purpose,
        structured_answer_message_id="message-1",
    )


def _fields(*names: str) -> list[dict[str, str]]:
    return [
        {"name": name, "field_type": "number", "description": f"The {name}."}
        for name in names
    ]


def _fee_steps(
    *, calculate_reads: list[str] | None, decide_reads: list[str] | None
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = [
        {
            "name": "Read notices",
            "instructions": "Read the income from the uploaded notices.",
            "output_fields": _fields("income"),
        },
        {
            "name": "Calculate fee",
            "instructions": "Subtract the rent from the income.",
            "output_fields": _fields("fee"),
        },
        {
            "name": "Write decision",
            "instructions": "Write the fee decision, stating the rent.",
        },
    ]
    for step, reads in zip(steps[1:], (calculate_reads, decide_reads), strict=True):
        if reads is not None:
            step["uses_form_fields"] = reads
    return steps


def _compile(
    steps: list[dict[str, Any]],
    *,
    purpose: RuntimeMetadataFieldPurpose = "interpret_input",
    **context: Any,
) -> FlowDraftSpecCore:
    intent = parse_create_flow_intent_arguments(
        {"flow_name": "Fee", "plan_rationale": "Compute a fee.", "steps": steps}
    )
    return compile_create_intent_to_spec(
        intent,
        context=CreateCompileContext(
            runtime_input_type=context.pop("runtime_input_type", InputType.DOCUMENT),
            runtime_input_fields=(_runtime_field("hyra", purpose),),
            **context,
        ),
    )


def _rejection(
    steps: list[dict[str, Any]], **context: Any
) -> AIBuilderArchitectureError:
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        _compile(steps, **context)
    return exc_info.value


def _question(step: StepSpec) -> str:
    return effective_question_binding(step.input_bindings) or ""


def _runtime_input(
    spec: FlowDraftSpecCore, *, order: int, hyra: int, prior: dict[int, Any]
) -> str:
    """What the runtime hands saved step `order` of the created flow when the
    run form says `hyra` and earlier steps returned the `prior` objects."""

    saved = compile_flow_draft_changeset(
        spec, current_flow=None, default_transcription_model_id=uuid4()
    ).compiled_steps[order - 1]
    results: list[FlowStepResult] = []
    for prior_order, structured in prior.items():
        result = completed_result(prior_order, str(structured))
        result.output_payload_json = {"text": str(structured), "structured": structured}
        results.append(result)
    resolved = resolve_step_input_binding(
        step=RuntimeStep(
            step_id=uuid4(),
            step_order=order,
            assistant_id=uuid4(),
            user_description=saved.user_description,
            input_source=saved.input_source.value,
            input_bindings=dict(saved.input_bindings or {}),
            input_config=None,
            output_mode=saved.output_mode.value,
            output_config=None,
            output_type=saved.output_type.value,
            input_type=saved.input_type.value,
        ),
        run=cast(FlowRun, SimpleNamespace(input_payload_json={"hyra": hyra})),
        prior_results=results,
        state=None,
        runtime_input_metadata=None,
        variable_resolver=FlowVariableResolver(),
    )
    assert resolved is not None
    # The run's evidence names the form read the step consumed, and its value.
    form_reads = [edge for edge in resolved.edges if edge.source.kind == "flow_input"]
    assert [edge.source.model_dump(mode="json") for edge in form_reads] == [
        {"kind": "flow_input", "selector": {"kind": "json_path", "path": ["hyra"]}}
    ]
    assert form_reads[0].selection.model_dump(mode="json")["sha256"] == (
        hashlib.sha256(json.dumps(hyra).encode()).hexdigest()
    )
    return resolved.text


def test_declared_consumers_read_the_run_value_beside_their_predecessor() -> None:
    spec = _compile(_fee_steps(calculate_reads=["hyra"], decide_reads=["hyra"]))

    # The purpose still places the field on the input reader.
    assert [_question(step).count(_READ) for step in spec.steps] == [1, 1, 1]
    calculate = spec.steps[1]
    # The calculation reads its predecessor's object and the form value as one
    # composed text input; the source ref keeps the predecessor's facts.
    assert calculate.input_source is InputSource.PREVIOUS_STEP
    assert calculate.input_type is InputType.TEXT
    assert calculate.input_contract is None
    assert calculate.input_bindings is not None
    assert [
        (ref["step_ref"], ref["output"])
        for ref in calculate.input_bindings["source_refs"]
    ] == [("step_a", "structured")]
    assert validate_spec(spec).valid

    for hyra in (7480, 9120):
        calculation_input = _runtime_input(
            spec, order=2, hyra=hyra, prior={1: {"income": 21000}}
        )
        decision_input = _runtime_input(
            spec, order=3, hyra=hyra, prior={1: {"income": 21000}, 2: {"fee": 735}}
        )
        assert "21000" in calculation_input
        assert f"hyra: {hyra}" in calculation_input
        assert "735" in decision_input
        assert f"hyra: {hyra}" in decision_input


def test_template_fill_calculation_reads_the_declared_field() -> None:
    steps = _fee_steps(calculate_reads=["hyra"], decide_reads=None)
    steps[-1]["output_fields"] = [
        {"name": "decision_text", "field_type": "string", "description": "Text."}
    ]
    spec = _compile(
        steps,
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
        selected_template_placeholders=("decision_text",),
    )

    calculate = next(step for step in spec.steps if step.name == "Calculate fee")
    assert _READ in _question(calculate)
    assert calculate.input_type is InputType.TEXT
    calculation_order = spec.steps.index(calculate) + 1
    calculation_input = _runtime_input(
        spec,
        order=calculation_order,
        hyra=7480,
        prior={order: {"income": 21000} for order in range(1, calculation_order)},
    )
    assert "21000" in calculation_input
    assert "hyra: 7480" in calculation_input


def test_no_declaration_keeps_purpose_placement() -> None:
    spec = _compile(_fee_steps(calculate_reads=None, decide_reads=None))

    assert [_question(step).count(_READ) for step in spec.steps] == [1, 0, 0]


def test_declaration_adds_to_the_confirmed_purpose_never_replaces_it() -> None:
    steps = _fee_steps(calculate_reads=None, decide_reads=None)
    steps[0]["uses_form_fields"] = ["hyra"]

    spec = _compile(steps, purpose="shape_result")

    assert [_question(step).count(_READ) for step in spec.steps] == [1, 0, 1]


def test_fan_in_consumer_is_a_repairable_rejection() -> None:
    error = _rejection(
        [
            {"name": "First note", "instructions": "Write the first note."},
            {"name": "Second note", "instructions": "Write the second note."},
            {
                "name": "Combine notes",
                "instructions": "Combine both notes for the rent.",
                "uses_form_fields": ["hyra"],
            },
        ],
        runtime_input_type=InputType.TEXT,
        aggregation_intent="aggregate",
    )

    assert error.log_context["reason"] == "all_previous_step_cannot_use_explicit_refs"
    assert error.repair_disposition == "model_correctable"
    assert error.log_context["step_index"] == 3
    assert "'Combine notes' lists 'hyra'" in (error.detail or "")
    assert "step 1 'First note', step 2 'Second note'" in (error.detail or "")


def test_explicit_previous_refs_on_a_fan_in_step_stop_at_the_one_explicit_ref_check() -> (
    None
):
    # The provider contract cannot author previous-step refs; a semantic step
    # that carries them, fan-in or not, is refused before any input wiring.
    intent = CreateFlowIntent.model_construct(
        flow_name="Notes",
        flow_description=None,
        plan_rationale="Combine notes.",
        assumptions=[],
        steps=[
            SemanticStepIntent(name="First note", instructions="Write a note."),
            SemanticStepIntent(name="Second note", instructions="Write a note."),
            SemanticStepIntent(
                name="Combine notes",
                instructions="Combine both notes.",
                uses_previous_fields=[
                    PreviousFieldRef(from_step=1, field_path="summary")
                ],
            ),
        ],
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_create_intent_to_spec(
            intent,
            context=CreateCompileContext(aggregation_intent="aggregate"),
        )

    assert exc_info.value.log_context["reason"] == "explicit_refs_not_supported"
    assert exc_info.value.log_context["step_index"] == 3


def test_dropped_render_helper_read_is_reported_on_the_helper() -> None:
    error = _rejection(
        [
            {"name": "First note", "instructions": "Write the first note."},
            {"name": "Second note", "instructions": "Write the second note."},
            {"name": "Combine notes", "instructions": "Combine both notes."},
            {
                "name": "Render PDF",
                "instructions": "Render the combined text as PDF with the rent.",
                "uses_form_fields": ["hyra"],
            },
        ],
        runtime_input_type=InputType.TEXT,
        aggregation_intent="aggregate",
        final_output_type=OutputType.PDF,
        final_output_mode=OutputMode.RENDER_VERBATIM,
    )

    # The helper's work runs in the fan-in step, which cannot read the field;
    # the model listed it on step 4, so step 4 is the step to change.
    assert error.log_context["reason"] == "all_previous_step_cannot_use_explicit_refs"
    assert error.log_context["step_index"] == 4
    assert "'Render PDF' lists 'hyra'" in (error.detail or "")
    assert "step 1 'First note', step 2 'Second note'" in (error.detail or "")


def test_json_run_input_reader_consumer_is_a_repairable_rejection() -> None:
    error = _rejection(
        [
            {
                "name": "Calculate fee",
                "instructions": "Calculate the fee.",
                "output_fields": _fields("fee"),
                "uses_form_fields": ["hyra"],
            }
        ],
        runtime_input_type=InputType.JSON,
        final_output_type=OutputType.JSON,
    )

    assert error.log_context["reason"] == "form_field_no_legal_target"
    assert error.repair_disposition == "model_correctable"
    assert error.log_context["step_index"] == 1
    assert "reads the run's JSON input" in (error.detail or "")


def test_declaration_on_the_purpose_target_reads_the_field_once() -> None:
    steps = _fee_steps(calculate_reads=None, decide_reads=None)
    steps[0]["uses_form_fields"] = ["hyra"]

    spec = _compile(steps)

    assert [_question(step).count(_READ) for step in spec.steps] == [1, 0, 0]
    assert validate_spec(spec).valid


def test_pure_transcription_consumer_is_a_repairable_rejection() -> None:
    error = _rejection(
        [
            {
                "name": "Transcribe meeting",
                "instructions": "Transcribe the recording.",
                "uses_form_fields": ["hyra"],
            }
        ],
        runtime_input_type=InputType.AUDIO,
        final_output_type=OutputType.TEXT,
        final_output_mode=OutputMode.TRANSCRIBE_ONLY,
        pattern_ids=("audio_transcription",),
    )

    assert error.log_context["reason"] == "pure_audio_transcription_shape_unsupported"
    assert error.repair_disposition == "model_correctable"


def _report_steps(
    *, section_reads: list[str] | None, body_reads: list[str] | None
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = [
        {
            "name": "Read documents",
            "instructions": "Read every document.",
            "output_fields": [
                {
                    "name": "documents",
                    "field_type": "array",
                    "description": "One item per document.",
                    "children": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Summary.",
                        }
                    ],
                }
            ],
        },
        {
            "name": "Build sections",
            "instructions": "Write one section per source.",
            "output_fields": [
                {
                    "name": "source_sections",
                    "field_type": "array",
                    "description": "Sections.",
                    "children": [
                        {
                            "name": "section_title",
                            "field_type": "string",
                            "description": "Section title.",
                        },
                        {
                            "name": "section_body",
                            "field_type": "string",
                            "description": "Section text.",
                        },
                    ],
                }
            ],
        },
        {
            "name": "Write overview",
            "instructions": "Write an overview of all sources.",
            "output_fields": [
                {"name": "overview", "field_type": "string", "description": "Text."}
            ],
        },
        {
            "name": "Assemble report",
            "instructions": "Assemble the final report for the rent.",
        },
    ]
    for index, reads in ((1, section_reads), (3, body_reads)):
        if reads is not None:
            steps[index]["uses_form_fields"] = reads
    return steps


_REPORT_CONTEXT: dict[str, Any] = {
    "final_output_type": OutputType.PDF,
    "final_output_mode": OutputMode.PASS_THROUGH,
    "runtime_max_files": 4,
    "aggregation_intent": "aggregate",
    "report_disposition": "both",
    "source_reader_required_fields": (
        SourceCaptureField(name="summary", description="Summary of the source."),
    ),
}


def test_item_mapped_consumer_is_a_repairable_rejection() -> None:
    error = _rejection(
        _report_steps(section_reads=["hyra"], body_reads=None), **_REPORT_CONTEXT
    )

    assert error.log_context["reason"] == "form_field_no_legal_target"
    assert error.repair_disposition == "model_correctable"
    assert error.log_context["step_index"] == 2
    assert "'Build sections' lists 'hyra'" in (error.detail or "")
    assert "runs once per item" in (error.detail or "")


def test_report_writer_read_folded_into_a_mapped_writer_names_the_writer() -> None:
    error = _rejection(
        _report_steps(section_reads=None, body_reads=["hyra"]),
        **{**_REPORT_CONTEXT, "report_disposition": "per_source_sections"},
    )

    assert error.log_context["reason"] == "form_field_no_legal_target"
    assert error.log_context["step_index"] == 4
    assert "'Assemble report' lists 'hyra'" in (error.detail or "")
    assert (
        "Steps that can read it: step 1 'Read documents', step 3 'Write overview'."
    ) in (error.detail or "")


def test_single_step_mapped_report_says_no_step_can_read() -> None:
    error = _rejection(
        [
            {
                "name": "Write report",
                "instructions": "Write a report for the rent.",
                "uses_form_fields": ["hyra"],
            }
        ],
        **{**_REPORT_CONTEXT, "report_disposition": "per_source_sections"},
    )

    assert error.log_context["step_index"] == 1
    assert "'Write report' lists 'hyra'" in (error.detail or "")
    assert "No proposed step can read" in (error.detail or "")


def test_folded_report_writer_reads_land_on_the_retained_writer() -> None:
    spec = _compile(
        _report_steps(section_reads=None, body_reads=["hyra"]), **_REPORT_CONTEXT
    )

    reads = {step.name: _question(step).count(_READ) for step in spec.steps}
    # The body writer's semantics fold into the overview writer; the compose
    # step that replaces it assembles sections and reads no form field.
    assert reads["Write overview"] == 1
    assert reads["Assemble report"] == 0
    assert validate_spec(spec).valid


def test_dropped_render_helper_hands_its_reads_to_the_step_before_it() -> None:
    spec = _compile(
        [
            {
                "name": "Read notices",
                "instructions": "Read the income.",
                "output_fields": _fields("income"),
            },
            {"name": "Write decision", "instructions": "Write the fee decision."},
            {
                "name": "Render PDF",
                "instructions": "Render the decision as a PDF with the rent.",
                "uses_form_fields": ["hyra"],
            },
        ],
        final_output_type=OutputType.PDF,
        final_output_mode=OutputMode.RENDER_VERBATIM,
    )

    reads = {step.name: _question(step).count(_READ) for step in spec.steps}
    assert reads["Write decision"] == 1


def test_create_schema_offers_exactly_the_confirmed_inputs() -> None:
    catalog = build_ai_builder_resource_catalog(available_models=[], available_kbs=[])
    schema = build_create_flow_tool_schema(
        resource_catalog=catalog,
        tool_name="propose_flow",
        confirmed_runtime_inputs=(
            ConfirmedRuntimeInputRequirement(name="hyra", purpose="interpret_input"),
            ConfirmedRuntimeInputRequirement(name="timmar", purpose="whole_flow"),
        ),
    )

    reads = schema["function"]["parameters"]["properties"]["steps"]["items"][
        "properties"
    ]["uses_form_fields"]
    assert reads["type"] == ["array", "null"]
    assert reads["items"]["enum"] == ["hyra", "timmar"]
    strict = build_native_strict_tool_schema(schema)
    assert (
        "uses_form_fields"
        in (
            strict["function"]["parameters"]["properties"]["steps"]["items"]["required"]
        )
    )
    arguments = {
        "flow_name": "Fee",
        "plan_rationale": "Compute a fee.",
        "steps": [
            {
                "name": "Calculate",
                "instructions": "Calculate the fee.",
                "output_fields": _fields("fee"),
                "uses_form_fields": ["rent"],
            }
        ],
    }
    with pytest.raises(ProposalToolArgumentsError):
        validate_propose_flow_tool_arguments(arguments=arguments, tool_schema=schema)

    for without_inputs in (
        build_create_flow_tool_schema(resource_catalog=catalog, tool_name="p"),
        build_create_flow_tool_schema(
            resource_catalog=catalog,
            tool_name="p",
            is_pure_audio_transcription=True,
            confirmed_runtime_inputs=(
                ConfirmedRuntimeInputRequirement(name="hyra", purpose="whole_flow"),
            ),
        ),
    ):
        step_properties = without_inputs["function"]["parameters"]["properties"][
            "steps"
        ]["items"]["properties"]
        assert "uses_form_fields" not in step_properties


def _saved_steps(
    spec: FlowDraftSpecCore,
) -> tuple[list[FlowStep], dict[Any, AssistantAuthoringSnapshot]]:
    steps = [
        FlowStep(
            id=uuid4(),
            flow_id=uuid4(),
            tenant_id=uuid4(),
            assistant_id=uuid4(),
            step_order=order,
            user_description=step.name,
            input_source=step.input_source.value,
            input_type=step.input_type.value,
            output_mode=step.output_mode.value,
            output_type=step.output_type.value,
            input_bindings=step.input_bindings,
            input_config=step.input_config,
            output_contract=step.output_contract,
            output_config=step.output_config,
        )
        for order, step in enumerate(spec.steps, 1)
    ]
    snapshots = {
        saved.assistant_id: AssistantAuthoringSnapshot(
            instructions=step.assistant_spec.instructions
        )
        for saved, step in zip(steps, spec.steps, strict=True)
    }
    return steps, snapshots


@pytest.mark.parametrize("edited_order", [1, 2])
def test_declared_reads_survive_an_instruction_edit(edited_order: int) -> None:
    created = _compile(_fee_steps(calculate_reads=["hyra"], decide_reads=["hyra"]))
    saved_steps, snapshots = _saved_steps(created)
    metadata = {
        "form_schema": {
            "fields": [
                field.model_dump(mode="json", exclude_none=True)
                for field in created.form_fields or ()
            ]
        }
    }

    result = compile_edit_proposal(
        OrderedEditProposal(
            plan_rationale="Clarify one step.",
            steps=[
                ModifyExistingStep(
                    existing_step_ref=f"existing_step_{order}",
                    **(
                        {
                            "assistant_spec": AssistantSpecPatch(
                                instructions="Do the same work, more carefully."
                            )
                        }
                        if order == edited_order
                        else {}
                    ),
                )
                for order in range(1, len(saved_steps) + 1)
            ],
        ),
        saved_steps,
        base_flow_revision=1,
        current_metadata_json=metadata,
        assistant_snapshots=snapshots,
    )

    for created_step, edited_step in zip(created.steps, result.spec.steps, strict=True):
        assert edited_step.input_bindings == created_step.input_bindings
    assert question_form_reads(result.spec.steps[1].input_bindings, ["hyra"]) == [
        "hyra"
    ]
