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
from eneo.flows.ai_builder.pattern_registry import (
    EXTRACT_TEMPLATE_VARIABLES_STEP,
    FLOW_INPUT_AUDIO_TRANSCRIPTION,
    FLOW_INPUT_DOCUMENT_UPLOAD,
    TEMPLATE_FILL_DOCX_STEP,
    TERMINAL_ARTIFACT_STEP,
)
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


def test_compiler_uses_assembly_path_for_whole_object_underlag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_old_skeleton_path(*args: object, **kwargs: object) -> object:
        raise AssertionError("broad previous-field flow should use FlowAssemblyPlan")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_create_compiler.materialize_step_skeleton",
        fail_old_skeleton_path,
    )
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
    expected_render_copy = f"Render {final_output_type.value.upper()}"
    assert renderer_step.name == expected_render_copy
    assert renderer_step.assistant_spec.instructions == expected_render_copy
    assert renderer_step.input_bindings is None
    assert compiled.document_body_writer_step_refs == (body_step.plan_step_ref,)
    assert validate_spec(compiled).valid


def test_compiler_uses_assembly_path_with_structural_pattern_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_old_skeleton_path(*args: object, **kwargs: object) -> object:
        raise AssertionError("structural pattern hint should use FlowAssemblyPlan")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_create_compiler.materialize_step_skeleton",
        fail_old_skeleton_path,
    )
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


def test_compiler_uses_assembly_path_for_document_source_reader_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_old_skeleton_path(*args: object, **kwargs: object) -> object:
        raise AssertionError("document source-reader flow should use FlowAssemblyPlan")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_create_compiler.materialize_step_skeleton",
        fail_old_skeleton_path,
    )
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
    assert body_step.input_type == InputType.JSON
    assert body_step.output_type == OutputType.TEXT
    assert renderer_step.input_source == InputSource.PREVIOUS_STEP
    assert renderer_step.input_type == InputType.TEXT
    assert renderer_step.output_type == OutputType.PDF
    assert renderer_step.output_mode == OutputMode.RENDER_VERBATIM
    assert renderer_step.input_bindings is None
    assert compiled.document_body_writer_step_refs == (body_step.plan_step_ref,)
    assert validate_spec(compiled).valid


def test_assembly_drops_source_contract_shadow_form_fields_before_lowering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_old_skeleton_path(*args: object, **kwargs: object) -> object:
        raise AssertionError(
            "source-contract shadow form fields should use FlowAssemblyPlan"
        )

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_create_compiler.materialize_step_skeleton",
        fail_old_skeleton_path,
    )
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
                }
            ],
            "steps": [
                {
                    "name": "Extract source facts",
                    "instructions": "Extract source facts from the document.",
                    "output_type": "json",
                    "uses_form_fields": ["manual_case_id"],
                    "output_fields": [
                        {
                            "name": "case_id",
                            "field_type": "string",
                            "description": "Case id found in the source.",
                        }
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
    assert validate_spec(compiled).valid


def test_compiler_uses_assembly_path_for_aggregate_document_body_fan_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_old_skeleton_path(*args: object, **kwargs: object) -> object:
        raise AssertionError("aggregate document flow should use FlowAssemblyPlan")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_create_compiler.materialize_step_skeleton",
        fail_old_skeleton_path,
    )
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
                            "name": "facts",
                            "field_type": "array",
                            "description": "Source facts.",
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
            aggregation_intent=cast(AggregationIntent, "aggregate"),
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
    assert body_step.input_source == InputSource.ALL_PREVIOUS_STEPS
    assert body_step.input_type == InputType.TEXT
    assert body_step.input_bindings is None
    assert renderer_step.input_source == InputSource.PREVIOUS_STEP
    assert renderer_step.input_type == InputType.TEXT
    assert renderer_step.output_mode == OutputMode.RENDER_VERBATIM
    assert renderer_step.input_bindings is None
    assert compiled.document_body_writer_step_refs == (body_step.plan_step_ref,)
    assert validate_spec(compiled).valid


def test_assembly_source_reader_contract_keeps_all_terminal_schema_leaves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_old_skeleton_path(*args: object, **kwargs: object) -> object:
        raise AssertionError(
            "terminal-schema source reader should use FlowAssemblyPlan"
        )

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_create_compiler.materialize_step_skeleton",
        fail_old_skeleton_path,
    )
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


def test_compiler_uses_assembly_path_for_pure_audio_transcription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_old_skeleton_path(*args: object, **kwargs: object) -> object:
        raise AssertionError("pure audio transcription should use FlowAssemblyPlan")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_create_compiler.materialize_step_skeleton",
        fail_old_skeleton_path,
    )
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


def test_compiler_uses_assembly_path_for_audio_report_with_semantic_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_old_skeleton_path(*args: object, **kwargs: object) -> object:
        raise AssertionError("audio report flow should use FlowAssemblyPlan")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_create_compiler.materialize_step_skeleton",
        fail_old_skeleton_path,
    )
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
    assert _question(body_step.input_bindings) == (
        "Summary: {{ step_b.output.structured.summary }}"
    )
    assert renderer_step.output_mode == OutputMode.RENDER_VERBATIM
    assert renderer_step.input_bindings is None
    assert compiled.document_body_writer_step_refs == (body_step.plan_step_ref,)
    assert validate_spec(compiled).valid


def test_compiler_uses_assembly_path_for_docx_template_fill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_old_skeleton_path(*args: object, **kwargs: object) -> object:
        raise AssertionError("DOCX template fill should use FlowAssemblyPlan")

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_create_compiler.materialize_step_skeleton",
        fail_old_skeleton_path,
    )
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
