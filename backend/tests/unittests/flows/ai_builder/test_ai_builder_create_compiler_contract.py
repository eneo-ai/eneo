from __future__ import annotations

from typing import cast

import pytest

from eneo.flows.ai_builder.ai_builder_create_compiler import (
    CreateCompileContext,
    compile_create_intent_to_spec,
    compile_create_steps_to_spec,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_validator import validate_spec
from eneo.flows.ai_builder.planning_state import AggregationIntent
from eneo.flows.flow_authoring_spec import (
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from eneo.flows.input_binding_contract_rules import effective_question_binding
from eneo.flows.output_processing import validate_against_contract


def _field(
    name: str,
    field_type: str = "string",
    *,
    description: str = "Beskrivning.",
) -> StructuredFieldDraft:
    return StructuredFieldDraft(
        name=name,
        field_type=field_type,
        description=description,
    )


def _question(input_bindings: dict[str, object] | None) -> str:
    question = effective_question_binding(input_bindings)
    assert question is not None
    return question


def test_compiler_uses_assembly_path_for_single_step_linear_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_old_skeleton_path(*args: object, **kwargs: object) -> object:
        raise AssertionError("single-step linear flow should use FlowAssemblyPlan")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_create_compiler.materialize_step_skeleton",
        fail_old_skeleton_path,
    )
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


def test_compiler_uses_assembly_path_for_linear_previous_field_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_old_skeleton_path(*args: object, **kwargs: object) -> object:
        raise AssertionError("linear previous-field flow should use FlowAssemblyPlan")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_create_compiler.materialize_step_skeleton",
        fail_old_skeleton_path,
    )
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
    assert _question(write_step.input_bindings) == (
        "Summary: {{ step_a.output.structured.summary }}"
    )
    assert validate_spec(compiled).valid


@pytest.mark.parametrize("final_output_type", [OutputType.PDF, OutputType.DOCX])
def test_compiler_uses_assembly_path_for_generated_document_renderer(
    monkeypatch: pytest.MonkeyPatch,
    final_output_type: OutputType,
) -> None:
    def fail_old_skeleton_path(*args: object, **kwargs: object) -> object:
        raise AssertionError("generated document flow should use FlowAssemblyPlan")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_create_compiler.materialize_step_skeleton",
        fail_old_skeleton_path,
    )
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
    assert renderer_step.input_bindings is None
    assert compiled.document_body_writer_step_refs == (body_step.plan_step_ref,)
    assert validate_spec(compiled).valid


def test_compiler_lowers_runtime_inputs_form_fields_and_previous_field_refs() -> None:
    compiled = compile_create_steps_to_spec(
        flow_name="Dokumentanalys",
        form_fields=[
            FormFieldSpec(
                name="referensnummer",
                label="Referensnummer",
                type="text",
                required=True,
            )
        ],
        steps=[
            NewStepDraft(
                name="Extrahera risker",
                instructions="Extrahera risker och rekommendationer.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                runtime_required=True,
                runtime_max_files=5,
                uses_form_fields=["referensnummer"],
                output_fields=[
                    _field("sammanfattning", description="Kort sammanfattning."),
                ],
            ),
            NewStepDraft(
                name="Skriv slutrapport",
                instructions="Skriv slutrapport med specifika datapunkter.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.TEXT,
                uses_previous_fields=[
                    {
                        "from_step": 1,
                        "field_path": "sammanfattning",
                        "label": "Sammanfattning",
                    }
                ],
            ),
        ],
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
    assert _question(compiled.steps[1].input_bindings) == (
        "Sammanfattning: {{ step_a.output.structured.sammanfattning }}"
    )
    assert validate_spec(compiled).valid


def test_source_reader_contract_keeps_all_terminal_schema_leaves() -> None:
    required_properties = {f"field_{index}": {"type": "string"} for index in range(10)}

    compiled = compile_create_steps_to_spec(
        flow_name="Dokumentanalys till JSON",
        terminal_output_schema={
            "type": "object",
            "properties": required_properties,
        },
        steps=[
            NewStepDraft(
                name="Läs källdokument",
                instructions="Extrahera källdata.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                output_fields=[_field("field_0")],
                runtime_required=True,
            ),
            NewStepDraft(
                name="Sammanställ resultat",
                instructions="Sammanställ slutlig JSON.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.JSON,
            ),
        ],
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
    validate_against_contract(
        {f"field_{index}": "value" for index in range(10)},
        terminal_contract,
        label="terminal output",
    )
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
