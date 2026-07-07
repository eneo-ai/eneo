from __future__ import annotations

from typing import cast

import pytest

from eneo.flows.ai_builder.ai_builder_create_compiler import (
    CreateCompileContext,
    compile_create_intent_to_spec,
    create_compile_context_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_fields import (
    RuntimeInputFieldHint,
)
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
    PlanningState,
    ResolvedSlot,
)
from eneo.flows.flow_authoring_spec import (
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from eneo.flows.input_binding_contract_rules import effective_question_binding


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


def test_compile_context_bridges_flow_input_type_to_authoring_input_type() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = _slot(
        "primary_runtime_input",
        "documents",
    )

    context = create_compile_context_from_planning_state(state)

    assert context is not None
    assert context.runtime_input_type == InputType.DOCUMENT


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
    expected_render_copy = f"Render {final_output_type.value.upper()}"
    assert renderer_step.name == expected_render_copy
    assert renderer_step.assistant_spec.instructions == expected_render_copy
    assert renderer_step.input_bindings is None
    assert compiled.document_body_writer_step_refs == (body_step.plan_step_ref,)
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


def test_assembly_places_server_owned_runtime_field_hints() -> None:
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
                            "name": "sammanfattning",
                            "field_type": "string",
                            "description": "Kort sammanfattning.",
                        },
                        {
                            "name": "saknade_uppgifter",
                            "field_type": "string",
                            "description": "Saknade uppgifter.",
                        },
                    ],
                },
                {
                    "name": "Skriv handläggarrapport",
                    "instructions": "Skriv en kort handläggarrapport.",
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
            runtime_metadata_state="detailed_case_metadata",
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


def test_compiler_uses_assembly_path_for_aggregate_document_body_fan_in() -> None:
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


def test_compiler_strips_audio_report_semantic_refs_and_uses_whole_object_underlag() -> (
    None
):
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
    assert body_step.input_bindings == {
        "source_refs": [{"step_ref": "step_b", "output": "structured"}]
    }
    assert renderer_step.output_mode == OutputMode.RENDER_VERBATIM
    assert renderer_step.input_bindings is None
    assert compiled.document_body_writer_step_refs == (body_step.plan_step_ref,)
    assert validate_spec(compiled).valid


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
                            "name": "sammanfattning",
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
                            "field_path": "sammanfattning",
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


def test_document_artifact_drops_model_authored_pdf_render_helper() -> None:
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
                    "instructions": (
                        "Omvandla den färdiga rapporttexten till en professionell "
                        "PDF med tydlig struktur och läsbar layout."
                    ),
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
            aggregation_intent=cast(AggregationIntent, "linear"),
        ),
    )

    assert [step.name for step in compiled.steps] == [
        "Identifiera dokumentens innehåll",
        "Skriv rapportinnehåll",
        "Render PDF",
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
    assert validate_spec(compiled).valid
