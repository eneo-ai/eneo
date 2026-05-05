from __future__ import annotations

import logging
from typing import cast

import pytest

from intric.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from intric.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from intric.flows.ai_builder.ai_builder_create_compiler import compile_create_draft
from intric.flows.ai_builder.ai_builder_create_dataflow import (
    normalize_create_draft_mechanics,
)
from intric.flows.ai_builder.ai_builder_create_models import (
    CreateFormFieldDraft,
    CreateStepDraft,
    FlowCreateDraft,
    StructuredFieldDraft,
)
from intric.flows.ai_builder.ai_builder_create_outline import (
    MAX_OUTLINE_STEPS,
    OutlineCompileContext,
    OutlineFlowArgumentError,
    attach_selected_mcp_refs_to_explicit_outline_steps,
    build_outline_flow_tool_schema,
    compile_outline_to_create_draft,
    outline_compile_context_from_planning_state,
    parse_outline_flow_arguments,
)
from intric.flows.ai_builder.ai_builder_create_validator import validate_create_draft
from intric.flows.ai_builder.ai_builder_flow_schema_values import (
    builder_output_type_values,
)
from intric.flows.ai_builder.ai_builder_models import (
    InputSource,
    InputType,
    OutputMode,
    OutputType,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
    canonicalize_create_draft_resources,
)
from intric.flows.ai_builder.ai_builder_runtime_input_fields import (
    DETAILED_CASE_METADATA,
    NO_EXTRA_RUNTIME_METADATA,
    RuntimeInputFieldHint,
    extract_runtime_input_field_hints,
)
from intric.flows.ai_builder.ai_builder_validator import validate_spec
from intric.flows.ai_builder.pattern_registry import (
    FLOW_INPUT_AUDIO_TRANSCRIPTION,
    STRUCTURED_EXTRACTION_STEP,
    TERMINAL_ARTIFACT_STEP,
)
from intric.flows.ai_builder.planning_state import (
    AggregationIntent,
    ArchitectureCommitDraft,
    PlanningState,
    ResolvedSlot,
    StepTriple,
)


def _field(
    name: str,
    field_type: str,
    *,
    description: str = "Beskrivning",
    required: bool = True,
    fields: list[StructuredFieldDraft] | None = None,
    item_fields: list[StructuredFieldDraft] | None = None,
) -> StructuredFieldDraft:
    return StructuredFieldDraft(
        name=name,
        field_type=field_type,
        description=description,
        required=required,
        fields=fields,
        item_fields=item_fields,
    )


def test_compile_create_draft_generates_runtime_upload_contracts_and_form_fields() -> (
    None
):
    draft = FlowCreateDraft(
        flow_name="Dokumentanalys",
        flow_description="Analyserar dokumentpaket.",
        plan_rationale="Strukturerad extraktion först för säkrare vidare analys.",
        assumptions=["PDF-paketet hör till ett och samma ärende."],
        form_fields=[
            CreateFormFieldDraft(
                variable_name="referensnummer",
                label="Referensnummer",
                field_type="text",
                required=True,
            ),
            CreateFormFieldDraft(
                variable_name="ansvarig_enhet",
                label="Ansvarig enhet",
                field_type="select",
                required=True,
                options=["Avdelning A", "Avdelning B"],
            ),
        ],
        steps=[
            CreateStepDraft(
                name="Extrahera strukturerad data",
                instructions="Extrahera viktiga datapunkter.",
                input_source="flow_input",
                input_type="document",
                output_type="json",
                runtime_upload=True,
                runtime_required=True,
                runtime_max_files=5,
                uses_form_fields=["referensnummer", "ansvarig_enhet"],
                output_fields=[
                    _field(
                        "risker",
                        "array",
                        description="Identifierade risker.",
                        item_fields=[
                            _field("titel", "string", description="Riskens namn."),
                            _field("nivå", "string", description="Risknivå."),
                        ],
                    ),
                    _field(
                        "konsekvenser",
                        "array",
                        description="Identifierade effekter.",
                        item_fields=[
                            _field(
                                "sammanfattning",
                                "string",
                                description="Kort summering.",
                            ),
                        ],
                    ),
                ],
            ),
            CreateStepDraft(
                name="Grounded sammanfattning",
                instructions="Skriv en grounded sammanfattning med källhänvisningar.",
                input_source="previous_step",
                input_type="json",
                output_type="text",
                citations_requested=True,
                knowledge_refs=["kb-risk"],
            ),
        ],
    )

    compiled = compile_create_draft(draft)

    assert compiled.flow_name == "Dokumentanalys"
    assert [step.plan_step_ref for step in compiled.steps] == ["step_a", "step_b"]
    assert compiled.form_fields is not None
    assert compiled.form_fields[0].name == "referensnummer"
    assert compiled.form_fields[1].options == ["Avdelning A", "Avdelning B"]

    first_step = compiled.steps[0]
    assert first_step.input_config is not None
    runtime_input = first_step.input_config["runtime_input"]
    assert runtime_input["enabled"] is True
    assert runtime_input["required"] is True
    assert runtime_input["max_files"] == 5
    assert runtime_input["input_format"] == "document"
    assert first_step.input_bindings == {
        "question": "{{ step_input.text }}\n\nreferensnummer: {{ referensnummer }}\nansvarig_enhet: {{ ansvarig_enhet }}"
    }
    assert "Required JSON fields:" in first_step.assistant_spec.instructions
    assert "risker" in first_step.assistant_spec.instructions
    assert "konsekvenser" in first_step.assistant_spec.instructions
    assert first_step.output_contract is not None
    assert first_step.output_contract["properties"]["risker"]["type"] == "array"
    assert (
        first_step.output_contract["properties"]["risker"]["items"]["properties"][
            "titel"
        ]["type"]
        == "string"
    )

    second_step = compiled.steps[1]
    assert second_step.input_bindings is None
    assert second_step.input_contract == first_step.output_contract
    assert second_step.output_config == {"citation_mode": "inline_inref_sidecar"}

    validation = validate_spec(compiled)
    assert validation.valid
    assert not any(
        warning.code == "contract_instruction_mismatch"
        for warning in validation.warnings
    )


def test_compile_create_draft_uses_previous_fields_to_generate_field_level_bindings() -> (
    None
):
    draft = FlowCreateDraft(
        flow_name="Dokumentanalys",
        plan_rationale="Återanvänd specifika fält i steg 3.",
        form_fields=[
            CreateFormFieldDraft(
                variable_name="referensnummer",
                label="Referensnummer",
                field_type="text",
                required=True,
            )
        ],
        steps=[
            CreateStepDraft(
                name="Extrahera risker",
                instructions="Extrahera risker och rekommendationer.",
                input_source="flow_input",
                input_type="document",
                output_type="json",
                runtime_upload=True,
                runtime_required=True,
                output_fields=[
                    _field(
                        "sammanfattning", "string", description="Kort sammanfattning."
                    ),
                    _field(
                        "risker",
                        "array",
                        description="Identifierade risker.",
                        item_fields=[
                            _field("rubrik", "string", description="Riskrubrik.")
                        ],
                    ),
                ],
            ),
            CreateStepDraft(
                name="Skriv slutrapport",
                instructions="Skriv slutrapport med specifika datapunkter.",
                input_source="previous_step",
                input_type="json",
                output_type="text",
                uses_form_fields=["referensnummer"],
                uses_previous_fields=[
                    {
                        "from_step": 1,
                        "field_path": "sammanfattning",
                        "label": "Sammanfattning",
                    },
                    {
                        "from_step": 1,
                        "field_path": "risker.0.rubrik",
                        "label": "Första riskrubrik",
                    },
                ],
            ),
        ],
    )

    compiled = compile_create_draft(draft)

    second_step = compiled.steps[1]
    assert second_step.input_bindings is not None
    assert second_step.input_bindings["question"] == (
        "Sammanfattning: {{ step_a.output.structured.sammanfattning }}\n\n"
        "Första riskrubrik: {{ step_a.output.structured.risker.0.rubrik }}\n\n"
        "referensnummer: {{ referensnummer }}"
    )


def test_compile_create_draft_keeps_previous_json_when_field_ref_is_non_adjacent() -> (
    None
):
    draft = FlowCreateDraft(
        flow_name="Protokoll",
        plan_rationale="Kombinera transkription och metadata.",
        steps=[
            CreateStepDraft(
                name="Strukturera transkription",
                instructions="Strukturera transkriptionen.",
                input_source="flow_input",
                input_type="text",
                output_type="json",
                output_fields=[
                    _field(
                        "transcription_text",
                        "string",
                        description="Full transkription.",
                    )
                ],
            ),
            CreateStepDraft(
                name="Identifiera metadata",
                instructions="Identifiera metadata.",
                input_source="previous_step",
                input_type="json",
                output_type="json",
                output_fields=[
                    _field("meeting_title", "string", description="Titel."),
                ],
            ),
            CreateStepDraft(
                name="Skapa protokoll",
                instructions="Skapa protokoll från metadata och transkription.",
                input_source="previous_step",
                input_type="text",
                output_type="text",
                uses_previous_fields=[
                    {
                        "from_step": 1,
                        "field_path": "transcription_text",
                        "label": "Transkription",
                    }
                ],
            ),
        ],
    )

    compiled = compile_create_draft(draft)

    third_step = compiled.steps[2]
    assert third_step.input_bindings is not None
    assert third_step.input_bindings["question"] == (
        "{{ step_b.output.structured }}\n\n"
        "Transkription: {{ step_a.output.structured.transcription_text }}"
    )


def test_compile_create_draft_keeps_previous_json_when_output_ref_is_non_adjacent() -> (
    None
):
    draft = FlowCreateDraft(
        flow_name="Protokoll",
        plan_rationale="Kombinera källtext och metadata.",
        steps=[
            CreateStepDraft(
                name="Transkribera ljud",
                instructions="Transkribera ljud.",
                input_source="flow_input",
                input_type="audio",
                output_type="text",
                runtime_upload=True,
                runtime_required=True,
            ),
            CreateStepDraft(
                name="Identifiera metadata",
                instructions="Identifiera metadata.",
                input_source="previous_step",
                input_type="text",
                output_type="json",
                output_fields=[
                    _field("meeting_title", "string", description="Titel."),
                ],
            ),
            CreateStepDraft(
                name="Skapa protokoll",
                instructions="Skapa protokoll från metadata och källtext.",
                input_source="previous_step",
                input_type="text",
                output_type="text",
                uses_previous_outputs=[
                    {
                        "from_step": 1,
                        "label": "Source material",
                    }
                ],
            ),
        ],
    )

    compiled = compile_create_draft(draft)

    third_step = compiled.steps[2]
    assert third_step.input_bindings is not None
    assert third_step.input_bindings["question"] == (
        "{{ step_b.output.structured }}\n\nSource material: {{ step_a.output.text }}"
    )


def test_compile_create_draft_all_previous_owns_source_over_previous_field_refs() -> (
    None
):
    draft = FlowCreateDraft(
        flow_name="Samlad analys",
        plan_rationale="Ett brett syntessteg ska använda implicit fan-in.",
        steps=[
            CreateStepDraft(
                name="Extrahera fakta",
                instructions="Extrahera fakta.",
                input_source="flow_input",
                input_type="text",
                output_type="json",
                output_fields=[
                    _field(
                        "sammanfattning", "string", description="Kort sammanfattning."
                    )
                ],
            ),
            CreateStepDraft(
                name="Bedöm fakta",
                instructions="Bedöm fakta.",
                input_source="previous_step",
                input_type="json",
                output_type="text",
            ),
            CreateStepDraft(
                name="Jämför allt",
                instructions="Jämför allt tidigare arbete.",
                input_source="all_previous_steps",
                input_type="text",
                output_type="text",
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

    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    third_step = compiled.steps[2]
    assert third_step.input_bindings is None
    assert "Beakta särskilt följande strukturerade fält" in (
        third_step.assistant_spec.instructions
    )
    assert "- Sammanfattning (steg 1: sammanfattning)" in (
        third_step.assistant_spec.instructions
    )
    assert validation.valid


def test_compile_create_draft_derives_transcribe_only_for_audio_upload() -> None:
    draft = FlowCreateDraft(
        flow_name="Transkribera ljud",
        plan_rationale="Starta med transkribering.",
        steps=[
            CreateStepDraft(
                name="Transkribera",
                instructions="Transkribera ljudfilen ordagrant.",
                input_source="flow_input",
                input_type="audio",
                output_type="text",
                runtime_upload=True,
                runtime_required=True,
            )
        ],
    )

    compiled = compile_create_draft(draft)

    step = compiled.steps[0]
    assert step.output_mode.value == "transcribe_only"
    assert step.input_bindings == {"question": "{{ step_input.text }}"}
    assert step.input_config is not None
    assert step.input_config["runtime_input"]["input_format"] == "audio"


def test_compile_create_draft_derives_template_fill_for_docx_templates() -> None:
    draft = FlowCreateDraft(
        flow_name="Mallstyrd rapport",
        plan_rationale="Använd DOCX-mall för sista steget.",
        steps=[
            CreateStepDraft(
                name="Generera rapport",
                instructions="Fyll DOCX-mallen med det strukturerade innehållet.",
                input_source="flow_input",
                input_type="text",
                output_type="docx",
                document_delivery_mode="template_fill",
            )
        ],
    )

    compiled = compile_create_draft(draft)

    assert compiled.steps[0].output_mode.value == "template_fill"


def test_validate_create_draft_rejects_template_fill_on_non_docx() -> None:
    draft = FlowCreateDraft(
        flow_name="Ogiltig mall",
        plan_rationale="Ogiltig kombination.",
        steps=[
            CreateStepDraft(
                name="PDF-steg",
                instructions="Generera PDF med mall.",
                input_source="flow_input",
                input_type="text",
                output_type="pdf",
                document_delivery_mode="template_fill",
            )
        ],
    )

    validation = validate_create_draft(draft)

    assert not validation.valid
    assert any(
        error.code == "template_fill_requires_docx" for error in validation.errors
    )


def test_validate_create_draft_rejects_unknown_previous_field_reference() -> None:
    draft = FlowCreateDraft(
        flow_name="Ogiltig fältreferens",
        plan_rationale="Testar fältvalidering.",
        steps=[
            CreateStepDraft(
                name="Extrahera risker",
                instructions="Extrahera risker.",
                input_source="flow_input",
                input_type="document",
                output_type="json",
                runtime_upload=True,
                output_fields=[_field("sammanfattning", "string")],
            ),
            CreateStepDraft(
                name="Sammanfatta",
                instructions="Skriv sammanfattning.",
                input_source="previous_step",
                input_type="json",
                output_type="text",
                uses_previous_fields=[{"from_step": 1, "field_path": "okänd"}],
            ),
        ],
    )

    validation = validate_create_draft(draft)

    assert not validation.valid
    assert any(
        error.code == "unknown_previous_field_reference" for error in validation.errors
    )


def test_validate_create_draft_rejects_non_json_previous_field_source() -> None:
    draft = FlowCreateDraft(
        flow_name="Ogiltig fältkälla",
        plan_rationale="Testar icke-json källa.",
        steps=[
            CreateStepDraft(
                name="Skriv text",
                instructions="Skriv text.",
                input_source="flow_input",
                input_type="text",
                output_type="text",
            ),
            CreateStepDraft(
                name="Sammanfatta",
                instructions="Sammanfatta.",
                input_source="previous_step",
                input_type="text",
                output_type="text",
                uses_previous_fields=[{"from_step": 1, "field_path": "titel"}],
            ),
        ],
    )

    validation = validate_create_draft(draft)

    assert not validation.valid
    assert any(
        error.code == "previous_field_source_requires_json_output"
        for error in validation.errors
    )


def test_validate_create_draft_rejects_non_text_previous_output_source() -> None:
    draft = FlowCreateDraft(
        flow_name="Ogiltig textkälla",
        plan_rationale="Testar icke-text källa.",
        steps=[
            CreateStepDraft(
                name="Extrahera fält",
                instructions="Extrahera fält.",
                input_source="flow_input",
                input_type="text",
                output_type="json",
                output_fields=[_field("titel", "string")],
            ),
            CreateStepDraft(
                name="Skriv rapport",
                instructions="Skriv rapport.",
                input_source="previous_step",
                input_type="text",
                output_type="text",
                uses_previous_outputs=[
                    {"from_step": 1, "label": "Källmaterial"},
                ],
            ),
        ],
    )

    validation = validate_create_draft(draft)

    assert not validation.valid
    assert any(
        error.code == "previous_output_source_requires_text_output"
        for error in validation.errors
    )


def test_validate_create_draft_rejects_file_flow_input_without_runtime_upload() -> None:
    draft = FlowCreateDraft(
        flow_name="Ogiltig filindata",
        plan_rationale="Testar runtime upload-krav.",
        steps=[
            CreateStepDraft(
                name="Analysera dokument",
                instructions="Analysera dokumentet.",
                input_source="flow_input",
                input_type="document",
                output_type="json",
                runtime_upload=False,
                output_fields=[_field("sammanfattning", "string")],
            )
        ],
    )

    validation = validate_create_draft(draft)

    assert not validation.valid
    assert any(
        error.code == "file_flow_input_requires_runtime_upload"
        for error in validation.errors
    )


def test_validate_create_draft_rejects_future_previous_field_source() -> None:
    draft = FlowCreateDraft(
        flow_name="Ogiltig stegref",
        plan_rationale="Testar framtida stegref.",
        steps=[
            CreateStepDraft(
                name="Steg 1",
                instructions="Steg 1.",
                input_source="flow_input",
                input_type="document",
                output_type="json",
                runtime_upload=True,
                output_fields=[_field("titel", "string")],
            ),
            CreateStepDraft(
                name="Steg 2",
                instructions="Steg 2.",
                input_source="previous_step",
                input_type="text",
                output_type="text",
                uses_previous_fields=[{"from_step": 2, "field_path": "titel"}],
            ),
        ],
    )

    validation = validate_create_draft(draft)

    assert not validation.valid
    assert any(
        error.code == "invalid_previous_field_source" for error in validation.errors
    )


def test_structured_field_depth_above_three_is_rejected() -> None:
    with pytest.raises(ValueError, match="nesting depth"):
        FlowCreateDraft(
            flow_name="För djup struktur",
            plan_rationale="Test",
            steps=[
                CreateStepDraft(
                    name="Extrahera",
                    instructions="Extrahera struktur.",
                    input_source="flow_input",
                    input_type="text",
                    output_type="json",
                    output_fields=[
                        _field(
                            "nivå_ett",
                            "object",
                            fields=[
                                _field(
                                    "nivå_två",
                                    "object",
                                    fields=[
                                        _field(
                                            "nivå_tre",
                                            "object",
                                            fields=[
                                                _field("nivå_fyra", "string"),
                                            ],
                                        ),
                                    ],
                                )
                            ],
                        )
                    ],
                )
            ],
        )


def test_canonicalize_create_draft_resources_resolves_names_to_refs() -> None:
    draft = FlowCreateDraft(
        flow_name="Resursupplösning",
        plan_rationale="Test",
        steps=[
            CreateStepDraft(
                name="Analys",
                instructions="Analysera underlaget.",
                input_source="flow_input",
                input_type="text",
                output_type="text",
                model_ref="gpt-5.4-nano",
                knowledge_refs=["Risk KB"],
            )
        ],
    )
    catalog = build_ai_builder_resource_catalog(
        available_models=[{"id": "model-1", "name": "gpt-5.4-nano"}],
        available_kbs=[{"id": "kb-1", "name": "Risk KB"}],
    )

    canonicalized, issues = canonicalize_create_draft_resources(draft, catalog=catalog)

    assert issues == []
    assert canonicalized.steps[0].model_ref == "model-1"
    assert canonicalized.steps[0].knowledge_refs == ["kb-1"]


def test_outline_flow_schema_hides_low_level_flow_mechanics() -> None:
    schema = build_outline_flow_tool_schema()
    assert schema["function"]["name"] == "outline_flow"
    step_props = schema["function"]["parameters"]["properties"]["steps"]["items"][
        "properties"
    ]

    assert "input_source" not in step_props
    assert "input_type" not in step_props
    assert "input_bindings" not in step_props
    assert "runtime_upload" not in step_props
    assert "output_mode" not in step_props
    assert "uses_previous_fields" not in step_props
    assert "uses_previous_outputs" not in step_props
    assert "uses_input_fields" in step_props
    assert "input_strategy" not in step_props


def test_outline_flow_schema_uses_flow_derived_enums() -> None:
    schema = build_outline_flow_tool_schema()
    parameters = schema["function"]["parameters"]
    properties = parameters["properties"]
    step_props = properties["steps"]["items"]["properties"]

    assert parameters["required"] == ["flow_name", "plan_rationale", "steps"]
    assert "runtime_input" not in properties
    assert "final_output_type" not in properties
    assert properties["steps"]["maxItems"] == MAX_OUTLINE_STEPS
    assert step_props["output_type"]["enum"] == [
        *builder_output_type_values(),
        None,
    ]


def test_outline_flow_schema_keeps_mcp_refs_free_form_for_small_catalog() -> None:
    schema = build_outline_flow_tool_schema(
        available_mcps=[
            {
                "ref": "server-1",
                "name": "Case system",
                "tools": [{"ref": "tool-1", "name": "lookup_case"}],
            }
        ]
    )
    step_props = schema["function"]["parameters"]["properties"]["steps"]["items"][
        "properties"
    ]

    assert "enum" not in step_props["mcp_server_refs"]["items"]
    assert "enum" not in step_props["mcp_tool_refs"]["items"]


def test_selected_mcp_server_is_attached_to_explicit_outline_step_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.INFO,
        logger="intric.flows.ai_builder.ai_builder_create_outline",
    )
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "tools": [{"id": "current-time", "name": "get_current_time"}],
            }
        ],
    )
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Tid till JSON",
            "plan_rationale": "Separera MCP-hämtning från slutlig strukturering.",
            "final_output_type": "json",
            "steps": [
                {
                    "name": "Hämta aktuell tid med Time MCP",
                    "task": "Använd Time MCP för att hämta aktuell tid.",
                    "output_type": "json",
                },
                {
                    "name": "Skapa strukturerat svar",
                    "task": "Formatera resultatet som JSON.",
                    "output_type": "json",
                },
            ],
        }
    )

    updated = attach_selected_mcp_refs_to_explicit_outline_steps(
        outline,
        selected_server_refs={"time-server"},
        catalog=catalog,
    )
    draft, issues = canonicalize_create_draft_resources(
        compile_outline_to_create_draft(updated),
        catalog=catalog,
    )

    assert issues == []
    assert draft.steps[0].mcp_server_refs == ["time-server"]
    assert draft.steps[0].mcp_tool_refs == ["current-time"]
    assert draft.steps[1].mcp_server_refs == []
    assert draft.steps[1].mcp_tool_refs == []
    record = next(
        (
            record
            for record in caplog.records
            if record.message
            == "ai_builder_selected_mcp_refs_attached_to_outline_steps"
        ),
        None,
    )
    assert record is not None
    assert record.patched_step_count == 1
    assert record.patched_steps == [
        {
            "step_name": "Hämta aktuell tid med Time MCP",
            "mcp_server_refs": ["time-server"],
            "mcp_tool_refs": [],
        }
    ]
    assert record.selected_mcp_server_refs == ["time-server"]


def test_selected_mcp_attachment_prefers_explicit_tool_aliases() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "tools": [
                    {"id": "current-time", "name": "get_current_time"},
                    {"id": "convert-time", "name": "convert_time"},
                ],
            }
        ],
    )
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Tid till JSON",
            "plan_rationale": "Använd bara relevant MCP-verktyg.",
            "final_output_type": "json",
            "steps": [
                {
                    "name": "Hämta tid med Time MCP",
                    "task": "Använd get_current_time för angiven tidszon.",
                    "output_type": "json",
                },
            ],
        }
    )

    updated = attach_selected_mcp_refs_to_explicit_outline_steps(
        outline,
        selected_server_refs={"time-server"},
        catalog=catalog,
    )
    draft, issues = canonicalize_create_draft_resources(
        compile_outline_to_create_draft(updated),
        catalog=catalog,
    )

    assert issues == []
    assert draft.steps[0].mcp_server_refs == ["time-server"]
    assert draft.steps[0].mcp_tool_refs == ["current-time"]


def test_selected_mcp_attachment_uses_explicit_tool_alias_without_server_name() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "tools": [
                    {"id": "current-time", "name": "get_current_time"},
                    {"id": "convert-time", "name": "convert_time"},
                ],
            }
        ],
    )
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Tid till JSON",
            "plan_rationale": "Verktygsnamnet räcker när användaren redan valt servern.",
            "final_output_type": "json",
            "steps": [
                {
                    "name": "Hämta aktuell tid",
                    "task": "Använd get_current_time för angiven tidszon.",
                    "output_type": "json",
                },
                {
                    "name": "Konvertera tiden",
                    "task": "Använd convert_time till Europe/Stockholm.",
                    "output_type": "json",
                },
            ],
        }
    )

    updated = attach_selected_mcp_refs_to_explicit_outline_steps(
        outline,
        selected_server_refs={"time-server"},
        catalog=catalog,
    )
    draft, issues = canonicalize_create_draft_resources(
        compile_outline_to_create_draft(updated),
        catalog=catalog,
    )

    assert issues == []
    assert draft.steps[0].mcp_server_refs == ["time-server"]
    assert draft.steps[0].mcp_tool_refs == ["current-time"]
    assert draft.steps[1].mcp_server_refs == ["time-server"]
    assert draft.steps[1].mcp_tool_refs == ["convert-time"]


def test_selected_mcp_attachment_skips_knowledge_steps() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[{"id": "kb-1", "name": "Policy"}],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "tools": [{"id": "current-time", "name": "get_current_time"}],
            }
        ],
    )
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Policy och tid",
            "plan_rationale": "Knowledge och MCP får inte blandas på samma steg.",
            "final_output_type": "json",
            "steps": [
                {
                    "name": "Grounda i policy",
                    "task": "Använd get_current_time endast som exempeltext här.",
                    "output_type": "text",
                    "knowledge_refs": ["kb-1"],
                },
            ],
        }
    )

    updated = attach_selected_mcp_refs_to_explicit_outline_steps(
        outline,
        selected_server_refs={"time-server"},
        catalog=catalog,
    )

    assert updated.steps[0].knowledge_refs == ["kb-1"]
    assert updated.steps[0].mcp_server_refs == []
    assert updated.steps[0].mcp_tool_refs == []


def test_selected_mcp_attachment_does_not_infer_from_domain_words() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[],
        available_kbs=[],
        available_mcps=[
            {
                "id": "time-server",
                "name": "Time MCP",
                "tools": [{"id": "current-time", "name": "get_current_time"}],
            }
        ],
    )
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Tid till JSON",
            "plan_rationale": "Domänord räcker inte för MCP-koppling.",
            "final_output_type": "json",
            "steps": [
                {
                    "name": "Hämta aktuell tid",
                    "task": "Hämta aktuell tid för användarens tidszon.",
                    "output_type": "json",
                },
            ],
        }
    )

    updated = attach_selected_mcp_refs_to_explicit_outline_steps(
        outline,
        selected_server_refs={"time-server"},
        catalog=catalog,
    )

    assert updated.steps[0].mcp_server_refs == []
    assert updated.steps[0].mcp_tool_refs == []


def test_outline_flow_schema_exposes_model_and_knowledge_refs_for_small_catalog() -> (
    None
):
    schema = build_outline_flow_tool_schema(
        available_models=[{"ref": "model-1", "name": "gpt-5.4-nano"}],
        available_kbs=[{"ref": "kb-1", "name": "Risk KB"}],
    )
    step_props = schema["function"]["parameters"]["properties"]["steps"]["items"][
        "properties"
    ]

    assert step_props["model_ref"]["enum"] == ["model-1", None]
    assert step_props["knowledge_refs"]["items"]["enum"] == ["kb-1"]


def test_outline_flow_schema_keeps_mcp_refs_free_form_for_malformed_catalog() -> None:
    schema = build_outline_flow_tool_schema(
        available_mcps=[
            {"ref": "", "tools": [{"ref": "ignored-tool"}]},
            {
                "ref": "server-1",
                "tools": [{"ref": ""}, {"ref": "tool-1", "name": "lookup_case"}],
            },
        ]
    )
    step_props = schema["function"]["parameters"]["properties"]["steps"]["items"][
        "properties"
    ]

    assert "enum" not in step_props["mcp_server_refs"]["items"]
    assert "enum" not in step_props["mcp_tool_refs"]["items"]


def test_outline_flow_schema_omits_mcp_ref_enums_for_large_catalog() -> None:
    schema = build_outline_flow_tool_schema(
        available_mcps=[
            {
                "ref": f"server-{index}",
                "tools": [{"ref": f"tool-{index}", "name": "lookup"}],
            }
            for index in range(16)
        ]
    )
    step_props = schema["function"]["parameters"]["properties"]["steps"]["items"][
        "properties"
    ]

    assert "enum" not in step_props["mcp_server_refs"]["items"]
    assert "enum" not in step_props["mcp_tool_refs"]["items"]


def test_outline_flow_schema_keeps_mcp_refs_free_form_when_tool_catalog_is_large() -> (
    None
):
    schema = build_outline_flow_tool_schema(
        available_mcps=[
            {
                "ref": "server-1",
                "tools": [
                    {"ref": f"tool-{index}", "name": "lookup"} for index in range(31)
                ],
            }
        ]
    )
    step_props = schema["function"]["parameters"]["properties"]["steps"]["items"][
        "properties"
    ]

    assert "enum" not in step_props["mcp_server_refs"]["items"]
    assert "enum" not in step_props["mcp_tool_refs"]["items"]


def test_parse_outline_flow_allows_server_owned_core_shape_defaults() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Minimal outline",
            "plan_rationale": "Let the backend apply the committed architecture.",
            "steps": [
                {
                    "name": "Do the work",
                    "task": "Follow the user's confirmed requirements.",
                }
            ],
        }
    )

    assert outline.runtime_input.input_type == "text"
    assert outline.final_output_type == "text"


def test_parse_outline_flow_accepts_create_resource_refs() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Kunskapsflöde",
            "plan_rationale": "Använder rätt modell och kunskapsbas.",
            "steps": [
                {
                    "name": "Analysera policy",
                    "task": "Svara med stöd av policyunderlaget.",
                    "model_ref": " model-1 ",
                    "knowledge_refs": [" kb-1 ", "kb-1", ""],
                }
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)

    assert draft.steps[0].model_ref == "model-1"
    assert draft.steps[0].knowledge_refs == ["kb-1"]


def test_parse_outline_flow_rejects_knowledge_and_mcp_on_same_step() -> None:
    with pytest.raises(OutlineFlowArgumentError, match="knowledge_refs with MCP refs"):
        parse_outline_flow_arguments(
            {
                "flow_name": "Ogiltigt",
                "plan_rationale": "Blandar två externa resurslägen.",
                "steps": [
                    {
                        "name": "Analysera",
                        "task": "Analysera med allt.",
                        "knowledge_refs": ["kb-1"],
                        "mcp_tool_refs": ["tool-1"],
                    }
                ],
            }
        )


def test_parse_outline_flow_errors_are_safe_and_field_level() -> None:
    with pytest.raises(OutlineFlowArgumentError) as exc_info:
        parse_outline_flow_arguments(
            {
                "flow_name": "Broken outline",
                "plan_rationale": "Contains a malformed step.",
                "steps": [
                    {
                        "name": "Extract",
                        "task": "Secret case note that should not appear in logs.",
                        "unexpected_mechanic": "Secret low-level binding detail.",
                    }
                ],
            }
        )

    message = str(exc_info.value)
    assert "steps.0.unexpected_mechanic" in message
    assert "Secret case note" not in message
    assert "Secret low-level binding detail" not in message
    assert "input_value" not in message


def test_parse_outline_flow_ignores_stale_backend_owned_step_mechanics() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Stale mechanics outline",
            "plan_rationale": "Stale models may emit low-level mechanics.",
            "steps": [
                {
                    "name": "Do the work",
                    "task": "Follow the user's confirmed requirements.",
                    "input_strategy": "all_prior_work",
                    "input_source": "all_previous_steps",
                    "input_type": "json",
                    "input_bindings": {"question": "{{ step_a.output.text }}"},
                    "runtime_upload": True,
                    "uses_previous_fields": [{"from_step": 1, "field_path": "x"}],
                }
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)

    assert draft.steps[0].input_source.value == "flow_input"
    assert draft.steps[0].input_type.value == "text"


def test_parse_outline_flow_ignores_step_only_fields_at_root() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Root noise outline",
            "plan_rationale": "Weak models may place step-only fields at root.",
            "uses_input_fields": ["audience"],
            "citations_requested": True,
            "output_type": "json",
            "steps": [
                {
                    "name": "Do the work",
                    "task": "Follow the user's confirmed requirements.",
                }
            ],
        }
    )

    assert outline.flow_name == "Root noise outline"
    assert len(outline.steps) == 1


def test_parse_outline_flow_attaches_orphan_field_specs_to_previous_step() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Orphan field outline",
            "plan_rationale": "Weak models may put output field specs in steps[].",
            "steps": [
                {
                    "name": "Extract facts",
                    "task": "Extract structured facts.",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "facts",
                            "field_type": "array",
                            "description": "Extracted facts.",
                            "item_fields": [
                                {
                                    "name": "fact",
                                    "field_type": "string",
                                    "description": "Fact text.",
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "extraction_notes",
                    "field_type": "array",
                    "description": "Notes about extraction quality.",
                    "item_fields": [
                        {
                            "name": "note",
                            "field_type": "string",
                            "description": "A quality note.",
                        }
                    ],
                },
                {
                    "name": "Write report",
                    "task": "Write the final report.",
                    "output_type": "text",
                },
            ],
        }
    )

    assert len(outline.steps) == 2
    assert outline.steps[0].output_fields is not None
    assert [field.name for field in outline.steps[0].output_fields] == [
        "facts",
        "extraction_notes",
    ]


def test_outline_flow_truncates_over_deep_structured_fields_before_draft_validation() -> (
    None
):
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Nested outline",
            "plan_rationale": "Weak models may over-nest JSON fields.",
            "steps": [
                {
                    "name": "Extract",
                    "task": "Extract nested facts.",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "level_one",
                            "field_type": "object",
                            "fields": [
                                {
                                    "name": "level_two",
                                    "field_type": "object",
                                    "fields": [
                                        {
                                            "name": "level_three",
                                            "field_type": "object",
                                            "fields": [
                                                {
                                                    "name": "level_four",
                                                    "field_type": "string",
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)

    assert draft.steps[0].output_fields is not None
    level_one = draft.steps[0].output_fields[0]
    assert level_one.fields is not None
    level_two = level_one.fields[0]
    assert level_two.fields is not None
    level_three = level_two.fields[0]
    assert level_three.field_type == "string"
    assert level_three.fields is None


def test_parse_outline_flow_allows_advanced_step_counts_above_old_limit() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Advanced workflow",
            "plan_rationale": "The requested process has many meaningful phases.",
            "steps": [
                {
                    "name": f"Phase {index}",
                    "task": f"Perform semantic phase {index}.",
                }
                for index in range(1, 21)
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert len(outline.steps) == 20
    assert len(draft.steps) == 20
    assert [step.name for step in compiled.steps] == [
        f"Phase {index}" for index in range(1, 21)
    ]
    assert validation.valid


def test_parse_outline_flow_allows_advanced_step_counts_above_old_soft_cap() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Very advanced workflow",
            "plan_rationale": "Some valid enterprise processes need many phases.",
            "steps": [
                {
                    "name": f"Phase {index}",
                    "task": f"Perform semantic phase {index}.",
                }
                for index in range(1, 81)
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)

    assert len(outline.steps) == 80
    assert len(draft.steps) == 80


def test_parse_outline_flow_normalizes_malformed_array_item_fields() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Structured extraction",
            "plan_rationale": "Weak models may emit one field object instead of a list.",
            "steps": [
                {
                    "name": "Extract rows",
                    "task": "Extract row summaries.",
                    "output_fields": [
                        {
                            "name": "rows",
                            "field_type": "array",
                            "description": "Extracted rows.",
                            "item_fields": {
                                "name": "summary",
                                "type": "text",
                                "description": "Row summary.",
                            },
                        }
                    ],
                }
            ],
        }
    )

    field = (
        outline.steps[0].output_fields[0] if outline.steps[0].output_fields else None
    )

    assert field is not None
    assert field.field_type == "array"
    assert field.item_fields is not None
    assert [item.name for item in field.item_fields] == ["summary"]
    assert field.item_fields[0].field_type == "string"


def test_parse_outline_flow_normalizes_json_schema_like_output_fields() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Schema-like extraction",
            "plan_rationale": "Weak models often emit JSON Schema-like properties.",
            "steps": [
                {
                    "name": "Extract fields",
                    "task": "Extract structured fields.",
                    "output_fields": {
                        "properties": {
                            "case_id": {
                                "type": "string",
                                "description": "Case identifier.",
                            },
                            "scores": {
                                "type": "array",
                                "description": "Score rows.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {"type": "string"},
                                        "value": {"type": "number"},
                                    },
                                },
                            },
                        }
                    },
                }
            ],
        }
    )

    fields = outline.steps[0].output_fields

    assert fields is not None
    assert [field.name for field in fields] == ["case_id", "scores"]
    assert fields[0].field_type == "string"
    assert fields[1].field_type == "array"
    assert fields[1].item_fields is not None
    assert [field.name for field in fields[1].item_fields] == ["label", "value"]


def test_compile_outline_flow_derives_runtime_input_fields_and_final_docx() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Case report",
            "flow_description": "Analyzes uploaded source material.",
            "plan_rationale": "Extract structure first, then create the report.",
            "runtime_input": {
                "input_type": "document",
                "required": True,
                "max_files": 5,
            },
            "final_output_type": "docx",
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
                    "task": "Extract the key facts and open questions.",
                    "output_fields": [
                        {
                            "name": "facts",
                            "field_type": "array",
                            "description": "Key facts.",
                            "required": True,
                            "item_fields": [
                                {
                                    "name": "summary",
                                    "field_type": "string",
                                    "description": "Fact summary.",
                                    "required": True,
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "Quality check",
                    "task": "Check for missing information and uncertainty.",
                    "output_type": "text",
                    "uses_input_fields": ["case_id"],
                },
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)
    compiled = compile_create_draft(draft)

    assert [step.name for step in draft.steps] == [
        "Extract facts",
        "Quality check",
        "Create DOCX",
    ]
    assert draft.steps[0].input_source.value == "flow_input"
    assert draft.steps[0].input_type.value == "document"
    assert draft.steps[0].runtime_upload is True
    assert draft.steps[0].runtime_required is True
    assert draft.steps[0].runtime_max_files == 5
    assert draft.steps[0].output_type.value == "json"
    assert draft.steps[1].input_source.value == "previous_step"
    assert draft.steps[1].input_type.value == "text"
    assert draft.steps[1].uses_form_fields == ["case_id"]
    assert draft.steps[2].output_type.value == "docx"
    assert draft.steps[2].document_delivery_mode == "generated"

    assert compiled.form_fields is not None
    assert compiled.form_fields[0].name == "case_id"
    assert compiled.steps[1].input_bindings == {
        "question": "{{ step_a.output.structured }}\n\ncase_id: {{ case_id }}"
    }
    assert compiled.steps[2].input_bindings is None
    validation = validate_spec(compiled)
    assert validation.valid


def test_compile_outline_flow_drops_server_derived_hints_when_planner_did_not_reference_them() -> (
    None
):
    """Server-derived runtime field hints are suggestions for fields the
    user mentioned in free text. They are only added to `form_fields`
    when the planner actually references them via `uses_input_fields`
    on at least one step. Hints the planner ignored are dropped so they
    do not surface as orphan UI controls or trigger the semantic critic
    spuriously — the planner asked for a flow with no input fields and
    that is what they get.
    """
    from intric.flows.ai_builder.ai_builder_form_field_usage import (
        find_unused_form_fields,
    )

    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Review report",
            "plan_rationale": "Review source material and produce a report.",
            "steps": [
                {
                    "name": "Review",
                    "task": "Review the source material.",
                }
            ],
        }
    )
    context = outline_compile_context_from_planning_state(
        None,
        runtime_input_field_hints=(
            RuntimeInputFieldHint(variable_name="audience", label="Audience"),
            RuntimeInputFieldHint(variable_name="detail_level", label="Detail level"),
        ),
    )

    draft = compile_outline_to_create_draft(outline, context=context)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [field.variable_name for field in draft.form_fields] == []
    assert draft.steps[-1].uses_form_fields == []
    assert compiled.form_fields is None or compiled.form_fields == []
    assert validation.valid
    assert find_unused_form_fields(compiled) == []


def test_compile_outline_flow_keeps_hint_when_planner_referenced_it_via_uses_input_fields() -> (
    None
):
    """A server-derived hint completes the declaration when the planner
    referenced its variable name via `uses_input_fields` even without
    declaring an explicit `input_fields` entry. The compiler then wires
    the field into the step's underlag automatically — the planner
    needs only to mention the name once.
    """
    from intric.flows.ai_builder.ai_builder_form_field_usage import (
        find_unused_form_fields,
    )

    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Review report",
            "plan_rationale": "Review source material for the chosen audience.",
            "steps": [
                {
                    "name": "Review",
                    "task": "Review the source material for the chosen audience.",
                    "uses_input_fields": ["audience"],
                }
            ],
        }
    )
    context = outline_compile_context_from_planning_state(
        None,
        runtime_input_field_hints=(
            RuntimeInputFieldHint(variable_name="audience", label="Audience"),
            RuntimeInputFieldHint(variable_name="detail_level", label="Detail level"),
        ),
    )

    draft = compile_outline_to_create_draft(outline, context=context)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [field.variable_name for field in draft.form_fields] == ["audience"]
    assert draft.steps[0].uses_form_fields == ["audience"]
    assert compiled.form_fields is not None
    assert [field.name for field in compiled.form_fields] == ["audience"]
    first_question = compiled.steps[0].input_bindings or {}
    assert "{{ audience }}" in str(first_question.get("question") or "")
    assert validation.valid
    assert find_unused_form_fields(compiled) == []


def test_compile_outline_flow_includes_only_referenced_runtime_hints() -> None:
    from intric.flows.ai_builder.ai_builder_form_field_usage import (
        find_unused_form_fields,
    )

    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Review report",
            "plan_rationale": "Review source material for the chosen audience.",
            "steps": [
                {
                    "name": "Extract report facts",
                    "task": "Extract facts for the selected report type.",
                    "output_fields": [
                        {
                            "name": "facts",
                            "field_type": "array",
                            "description": "Relevant report facts.",
                            "required": True,
                            "item_fields": [
                                {
                                    "name": "fact",
                                    "field_type": "string",
                                    "description": "A fact.",
                                    "required": True,
                                }
                            ],
                        }
                    ],
                    "uses_input_fields": ["report_type"],
                },
                {
                    "name": "Review for audience",
                    "task": "Review the extracted facts for the chosen audience.",
                    "uses_input_fields": ["audience"],
                },
            ],
        }
    )
    context = outline_compile_context_from_planning_state(
        None,
        runtime_input_field_hints=(
            RuntimeInputFieldHint(variable_name="audience", label="Audience"),
            RuntimeInputFieldHint(variable_name="report_type", label="Report type"),
            RuntimeInputFieldHint(variable_name="detail_level", label="Detail level"),
        ),
    )

    draft = compile_outline_to_create_draft(outline, context=context)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [field.variable_name for field in draft.form_fields] == [
        "audience",
        "report_type",
    ]
    assert draft.steps[0].uses_form_fields == ["report_type"]
    assert draft.steps[1].uses_form_fields == ["audience"]
    assert compiled.form_fields is not None
    assert [field.name for field in compiled.form_fields] == [
        "audience",
        "report_type",
    ]
    assert find_unused_form_fields(compiled) == []
    assert validation.valid


def test_compile_outline_flow_drops_extracted_metadata_hints_when_planner_did_not_wire_them() -> (
    None
):
    prompt = (
        "Jag vill ha ett flöde för utvecklingssamtal där användaren kommer "
        "att ange namn, personnummer, yrke, roll och nuvarande lön och sedan "
        "ladda upp ljud från samtalet."
    )
    field_hints = extract_runtime_input_field_hints(prompt)
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Utvecklingssamtal",
            "plan_rationale": "Transkribera samtal och skapa en strukturerad bedömning.",
            "runtime_input": {"input_type": "audio", "required": True},
            "final_output_type": "json",
            "steps": [
                {
                    "name": "Transkribera samtal",
                    "task": "Transkribera ljudet från utvecklingssamtalet.",
                    "output_type": "text",
                },
                {
                    "name": "Analysera samtal",
                    "task": (
                        "Analysera transkriptionen och använd metadatafält vid "
                        "bedömningen."
                    ),
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "salary_increase_percent",
                            "field_type": "number",
                            "description": "Bedömd lönehöjning i procent.",
                            "required": True,
                        }
                    ],
                },
            ],
        }
    )
    context = outline_compile_context_from_planning_state(
        None,
        runtime_input_field_hints=field_hints,
    )

    draft = compile_outline_to_create_draft(outline, context=context)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    from intric.flows.ai_builder.ai_builder_form_field_usage import (
        find_unused_form_fields,
    )

    # The planner declared no `input_fields` and did not list any hint name
    # in `uses_input_fields`, so the server-derived hints stay out of
    # form_fields entirely. The flow validates without orphan UI controls.
    assert [field.variable_name for field in draft.form_fields] == []
    assert draft.steps[-1].uses_form_fields == []
    assert compiled.form_fields is None or compiled.form_fields == []
    assert validation.valid
    assert find_unused_form_fields(compiled) == []


def test_compile_outline_flow_overlap_planner_declared_field_and_hint_with_same_name() -> (
    None
):
    """When the planner declares an `input_fields` entry whose name
    matches a server-derived hint, the planner-declared label/options/etc
    win and the field appears exactly once in form_fields. The hint
    completes nothing because the declaration is already there.
    """
    from intric.flows.ai_builder.ai_builder_form_field_usage import (
        find_unused_form_fields,
    )

    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Overlap audience",
            "plan_rationale": "Use audience for tone.",
            "input_fields": [
                {
                    "variable_name": "audience",
                    "label": "Audience explicit",
                    "field_type": "text",
                    "required": False,
                }
            ],
            "steps": [
                {
                    "name": "Write",
                    "task": "Write for the audience.",
                    "uses_input_fields": ["audience"],
                }
            ],
        }
    )
    context = outline_compile_context_from_planning_state(
        None,
        runtime_input_field_hints=(
            RuntimeInputFieldHint(
                variable_name="audience", label="Audience hint label"
            ),
        ),
    )

    draft = compile_outline_to_create_draft(outline, context=context)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    # Field appears once and keeps the planner-declared label.
    assert [field.variable_name for field in draft.form_fields] == ["audience"]
    assert draft.form_fields[0].label == "Audience explicit"
    assert draft.steps[0].uses_form_fields == ["audience"]
    assert compiled.form_fields is not None
    assert [field.name for field in compiled.form_fields] == ["audience"]
    first_question = str((compiled.steps[0].input_bindings or {}).get("question") or "")
    assert first_question.count("{{ audience }}") == 1
    assert validation.valid
    assert find_unused_form_fields(compiled) == []


def test_compile_outline_flow_orphan_uses_input_fields_reference_is_dropped_silently() -> (
    None
):
    """When a step lists a name in `uses_input_fields` that exists in
    NEITHER `outline.input_fields` NOR any server-derived hint, the
    reference is silently dropped. The compiled spec is valid (no
    orphan template variable, no exception).
    """
    from intric.flows.ai_builder.ai_builder_form_field_usage import (
        find_unused_form_fields,
    )

    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Orphan reference",
            "plan_rationale": "Reference a name that does not exist.",
            "steps": [
                {
                    "name": "Write",
                    "task": "Write something useful.",
                    "uses_input_fields": ["missing_field"],
                }
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    # The orphan reference does not pull a field into form_fields and
    # does not poison the step's bindings with `{{ missing_field }}`.
    assert [field.variable_name for field in draft.form_fields] == []
    assert draft.steps[0].uses_form_fields == []
    first_question = str((compiled.steps[0].input_bindings or {}).get("question") or "")
    assert "{{ missing_field }}" not in first_question
    assert validation.valid
    assert find_unused_form_fields(compiled) == []


def test_compile_outline_flow_drops_field_that_shadows_primary_text_input(
    caplog: pytest.LogCaptureFixture,
) -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Customer reply",
            "plan_rationale": "Classify the request before drafting an answer.",
            "input_fields": [
                {
                    "variable_name": "text",
                    "label": "Text",
                    "field_type": "text",
                    "required": True,
                }
            ],
            "steps": [
                {
                    "name": "Classify request",
                    "task": "Classify the incoming customer request.",
                    "output_fields": [
                        {
                            "name": "category",
                            "field_type": "string",
                            "description": "Request category.",
                        }
                    ],
                },
                {
                    "name": "Draft reply",
                    "task": "Draft a concise reply based on the classification.",
                    "output_type": "text",
                    "uses_input_fields": ["text"],
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="text",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_text",
            source="structured_answer",
            confidence="high",
        ),
    }

    with caplog.at_level(
        logging.INFO,
        logger="intric.flows.ai_builder.ai_builder_create_outline",
    ):
        draft = compile_outline_to_create_draft(
            outline,
            context=outline_compile_context_from_planning_state(state),
        )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    shadow_records = [
        record
        for record in caplog.records
        if record.message == "ai_builder_primary_input_shadow_fields_dropped"
    ]
    assert shadow_records
    assert getattr(shadow_records[0], "field_names") == ["text"]
    assert getattr(shadow_records[0], "runtime_input_type") == "text"
    assert draft.form_fields == []
    assert draft.steps[1].uses_form_fields == []
    assert draft.steps[1].input_type.value == "json"
    assert compiled.form_fields is None
    assert compiled.steps[1].input_bindings is None
    assert validation.valid


def test_compile_outline_flow_keeps_secondary_text_metadata_for_text_input() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Audience aware reply",
            "plan_rationale": "Classify the request and adapt the response.",
            "input_fields": [
                {
                    "variable_name": "audience",
                    "label": "Audience",
                    "field_type": "text",
                    "required": False,
                }
            ],
            "steps": [
                {
                    "name": "Classify request",
                    "task": "Classify the incoming customer request.",
                    "output_fields": [
                        {
                            "name": "category",
                            "field_type": "string",
                            "description": "Request category.",
                        }
                    ],
                },
                {
                    "name": "Draft reply",
                    "task": "Draft a concise reply for the selected audience.",
                    "output_type": "text",
                    "uses_input_fields": ["audience"],
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="text",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_text",
            source="structured_answer",
            confidence="high",
        ),
    }

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [field.variable_name for field in draft.form_fields] == ["audience"]
    assert draft.steps[1].uses_form_fields == ["audience"]
    assert compiled.form_fields is not None
    assert compiled.steps[1].input_bindings == {
        "question": "{{ step_a.output.structured }}\n\naudience: {{ audience }}"
    }
    assert validation.valid


def test_compile_outline_flow_drops_runtime_fields_when_metadata_is_disabled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Kommunstyrelsemöte till DOCX",
            "plan_rationale": "Transkribera och strukturera mötet innan DOCX skapas.",
            "runtime_input": {"input_type": "audio", "required": True},
            "final_output_type": "docx",
            "input_fields": [
                {
                    "variable_name": "language",
                    "label": "Språk",
                    "field_type": "text",
                    "required": False,
                },
                {
                    "variable_name": "output_style",
                    "label": "Dokumentstil",
                    "field_type": "text",
                    "required": False,
                },
                {
                    "variable_name": "include_timestamps",
                    "label": "Inkludera tidsstämplar",
                    "field_type": "text",
                    "required": False,
                },
            ],
            "steps": [
                {
                    "name": "Transkribera ljud",
                    "task": "Transkribera den uppladdade ljudfilen.",
                    "output_type": "text",
                    "uses_input_fields": ["language"],
                },
                {
                    "name": "Identifiera rubriker",
                    "task": "Dela in mötet i kommunstyrelserubriker.",
                    "output_fields": [
                        {
                            "name": "sections",
                            "field_type": "object",
                            "description": "Rubrikindelat mötesinnehåll.",
                            "required": True,
                        }
                    ],
                    "uses_input_fields": ["output_style"],
                },
                {
                    "name": "Skriv dokumenttext",
                    "task": "Skriv slutlig dokumenttext.",
                    "output_type": "text",
                    "uses_input_fields": ["include_timestamps"],
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="audio",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="docx_document",
            source="structured_answer",
            confidence="high",
        ),
        "runtime_metadata_fields": ResolvedSlot(
            name="runtime_metadata_fields",
            value=NO_EXTRA_RUNTIME_METADATA,
            source="policy_default",
            confidence="medium",
        ),
    }

    with caplog.at_level(
        logging.INFO,
        logger="intric.flows.ai_builder.ai_builder_create_outline",
    ):
        draft = compile_outline_to_create_draft(
            outline,
            context=outline_compile_context_from_planning_state(state),
        )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    metadata_records = [
        record
        for record in caplog.records
        if record.message == "ai_builder_runtime_metadata_input_fields_dropped"
    ]
    assert metadata_records
    assert getattr(metadata_records[0], "field_names") == [
        "include_timestamps",
        "language",
        "output_style",
    ]
    assert getattr(metadata_records[0], "runtime_metadata_state") == (
        NO_EXTRA_RUNTIME_METADATA
    )
    assert draft.form_fields == []
    assert all(step.uses_form_fields == [] for step in draft.steps)
    assert compiled.form_fields is None
    question_bindings = [
        step.input_bindings["question"]
        for step in compiled.steps
        if step.input_bindings is not None
    ]
    assert not any("{{ language }}" in binding for binding in question_bindings)
    assert not any("{{ output_style }}" in binding for binding in question_bindings)
    assert not any(
        "{{ include_timestamps }}" in binding for binding in question_bindings
    )
    assert validation.valid


def test_compile_outline_flow_keeps_runtime_fields_when_metadata_is_detailed() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Audience aware reply",
            "plan_rationale": "Classify the request and adapt the response.",
            "input_fields": [
                {
                    "variable_name": "audience",
                    "label": "Audience",
                    "field_type": "text",
                    "required": False,
                }
            ],
            "steps": [
                {
                    "name": "Classify request",
                    "task": "Classify the incoming customer request.",
                    "output_fields": [
                        {
                            "name": "category",
                            "field_type": "string",
                            "description": "Request category.",
                        }
                    ],
                },
                {
                    "name": "Draft reply",
                    "task": "Draft a concise reply for the selected audience.",
                    "output_type": "text",
                    "uses_input_fields": ["audience"],
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="text",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_text",
            source="structured_answer",
            confidence="high",
        ),
        "runtime_metadata_fields": ResolvedSlot(
            name="runtime_metadata_fields",
            value=DETAILED_CASE_METADATA,
            source="structured_answer",
            confidence="high",
        ),
    }

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [field.variable_name for field in draft.form_fields] == ["audience"]
    assert draft.steps[1].uses_form_fields == ["audience"]
    assert compiled.form_fields is not None
    assert validation.valid


def test_compile_outline_flow_folds_leading_zero_contract_text_step(
    caplog: pytest.LogCaptureFixture,
) -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Customer reply",
            "plan_rationale": "Classify first, then draft the reply.",
            "runtime_input": {"input_type": "text", "required": True},
            "final_output_type": "text",
            "steps": [
                {
                    "name": "Receive question",
                    "task": "Use the customer question as the source material.",
                    "output_type": "text",
                },
                {
                    "name": "Classify request",
                    "task": "Classify the incoming request.",
                    "output_fields": [
                        {
                            "name": "category",
                            "field_type": "string",
                            "description": "Request category.",
                        }
                    ],
                },
                {
                    "name": "Draft reply",
                    "task": "Draft a concise customer reply.",
                    "output_type": "text",
                },
            ],
        }
    )

    with caplog.at_level(
        logging.INFO,
        logger="intric.flows.ai_builder.ai_builder_create_outline",
    ):
        draft = compile_outline_to_create_draft(outline)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    folded_records = [
        record
        for record in caplog.records
        if record.message == "ai_builder_outline_zero_contract_steps_folded"
    ]
    assert folded_records
    assert getattr(folded_records[0], "folded_step_names") == ["Receive question"]
    assert getattr(folded_records[0], "target_step_name") == "Classify request"
    assert [step.name for step in draft.steps] == ["Classify request", "Draft reply"]
    assert (
        draft.steps[0].instructions
        == "Use the customer question as the source material.\n\n"
        "Classify the incoming request."
    )
    assert draft.steps[0].input_source.value == "flow_input"
    assert draft.steps[0].input_type.value == "text"
    assert draft.steps[0].output_type.value == "json"
    assert compiled.steps[0].input_bindings == {"question": "{{ indata_text }}"}
    assert compiled.steps[1].input_type.value == "json"
    assert validation.valid


def test_compile_outline_flow_preserves_leading_step_with_output_contract() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Structured intake",
            "plan_rationale": "Extract structured fields before writing.",
            "runtime_input": {"input_type": "text", "required": True},
            "final_output_type": "text",
            "steps": [
                {
                    "name": "Extract intake",
                    "task": "Extract the source fields.",
                    "output_type": "text",
                    "output_fields": [
                        {
                            "name": "topic",
                            "field_type": "string",
                            "description": "Main topic.",
                        }
                    ],
                },
                {
                    "name": "Write answer",
                    "task": "Write the final answer.",
                    "output_type": "text",
                },
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == ["Extract intake", "Write answer"]
    assert draft.steps[0].output_fields is not None
    assert compiled.steps[1].input_contract == compiled.steps[0].output_contract
    assert validation.valid


def test_compile_outline_flow_preserves_leading_step_with_form_field_usage() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Audience reply",
            "plan_rationale": "Use runtime audience metadata while drafting.",
            "runtime_input": {"input_type": "text", "required": True},
            "final_output_type": "text",
            "input_fields": [
                {
                    "variable_name": "audience",
                    "label": "Audience",
                    "field_type": "text",
                    "required": False,
                }
            ],
            "steps": [
                {
                    "name": "Prepare audience context",
                    "task": "Prepare context for the selected audience.",
                    "output_type": "text",
                    "uses_input_fields": ["audience"],
                },
                {
                    "name": "Write answer",
                    "task": "Write the final answer.",
                    "output_type": "text",
                },
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Prepare audience context",
        "Write answer",
    ]
    assert draft.steps[0].uses_form_fields == ["audience"]
    assert compiled.steps[0].input_bindings == {
        "question": "{{ indata_text }}\n\naudience: {{ audience }}"
    }
    assert validation.valid


def test_compile_outline_flow_preserves_file_runtime_leading_step() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Document summary",
            "plan_rationale": "Prepare uploaded documents before summarizing.",
            "runtime_input": {"input_type": "document", "required": True},
            "final_output_type": "text",
            "steps": [
                {
                    "name": "Read documents",
                    "task": "Read the uploaded documents.",
                    "output_type": "text",
                },
                {
                    "name": "Summarize",
                    "task": "Summarize the document material.",
                    "output_type": "text",
                },
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == ["Read documents", "Summarize"]
    assert draft.steps[0].runtime_upload is True
    assert compiled.steps[0].input_config["runtime_input"]["input_format"] == "document"
    assert validation.valid


def test_compile_outline_flow_preserves_leading_step_with_model_ref() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Specialized first pass",
            "plan_rationale": "Use a selected model for the first pass.",
            "runtime_input": {"input_type": "text", "required": True},
            "final_output_type": "text",
            "steps": [
                {
                    "name": "Specialized reading",
                    "task": "Read the source text with the selected model.",
                    "output_type": "text",
                    "model_ref": "model-specialist",
                },
                {
                    "name": "Write answer",
                    "task": "Write the final answer.",
                    "output_type": "text",
                },
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Specialized reading",
        "Write answer",
    ]
    assert draft.steps[0].model_ref == "model-specialist"
    assert validation.valid


def test_compile_outline_flow_preserves_leading_step_with_knowledge_refs() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Policy grounded reply",
            "plan_rationale": "Ground the first pass in a selected knowledge base.",
            "runtime_input": {"input_type": "text", "required": True},
            "final_output_type": "text",
            "steps": [
                {
                    "name": "Ground in policy",
                    "task": "Read the source text against the policy base.",
                    "output_type": "text",
                    "knowledge_refs": ["kb-policy"],
                },
                {
                    "name": "Write answer",
                    "task": "Write the final answer.",
                    "output_type": "text",
                },
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == ["Ground in policy", "Write answer"]
    assert draft.steps[0].knowledge_refs == ["kb-policy"]
    assert validation.valid


def test_compile_outline_flow_folds_before_final_artifact_append() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "DOCX report",
            "plan_rationale": "Prepare source text and generate a report.",
            "runtime_input": {"input_type": "text", "required": True},
            "final_output_type": "docx",
            "steps": [
                {
                    "name": "Receive text",
                    "task": "Use the submitted text as report source.",
                    "output_type": "text",
                },
                {
                    "name": "Draft report content",
                    "task": "Draft the report body.",
                    "output_type": "text",
                },
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Draft report content",
        "Create DOCX",
    ]
    assert draft.steps[0].instructions == (
        "Use the submitted text as report source.\n\nDraft the report body."
    )
    assert draft.steps[-1].output_type.value == "docx"
    assert compiled.steps[-1].output_type.value == "docx"
    assert validation.valid


def test_runtime_input_field_hints_parse_generic_field_declarations() -> None:
    hints = extract_runtime_input_field_hints(
        "Use input fields for audience and detail level at runtime, then build a report."
    )

    assert [(hint.variable_name, hint.label) for hint in hints] == [
        ("audience", "audience"),
        ("detail_level", "detail level"),
    ]

    swedish_hints = extract_runtime_input_field_hints(
        "Använd inmatningsfält för målgrupp och rapportnivå vid körning, och skapa rapport."
    )

    assert [(hint.variable_name, hint.label) for hint in swedish_hints] == [
        ("malgrupp", "målgrupp"),
        ("rapportniva", "rapportnivå"),
    ]


def test_compile_outline_flow_uses_server_architecture_context_for_core_shape() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Audio report",
            "plan_rationale": "Transcribe and summarize.",
            "runtime_input": {"input_type": "text", "required": True},
            "final_output_type": "json",
            "steps": [
                {
                    "name": "Transcribe",
                    "task": "Transcribe the uploaded audio.",
                    "output_type": "text",
                },
                {
                    "name": "Summarize",
                    "task": "Summarize the transcript for the reader.",
                    "output_type": "text",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="audio",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="pdf_document",
            source="structured_answer",
            confidence="high",
        ),
    }

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.output_type.value for step in draft.steps] == [
        "text",
        "text",
        "pdf",
    ]
    assert draft.steps[0].input_type.value == "audio"
    assert draft.steps[0].runtime_upload is True
    assert draft.steps[2].document_delivery_mode == "generated"
    assert compiled.steps[0].input_config["runtime_input"]["input_format"] == "audio"
    assert compiled.steps[2].output_type.value == "pdf"
    assert validation.valid


def test_compile_outline_flow_inserts_audio_transcription_for_single_artifact_step() -> (
    None
):
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Audio PDF report",
            "plan_rationale": "Create a report from uploaded audio.",
            "steps": [
                {
                    "name": "Create report",
                    "task": "Summarize the recording and create the final PDF.",
                }
            ],
        }
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="audio",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="pdf_document",
            source="structured_answer",
            confidence="high",
        ),
    }

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Transcribe audio",
        "Create report",
        "Create PDF",
    ]
    assert draft.steps[0].input_type.value == "audio"
    assert draft.steps[0].output_type.value == "text"
    assert draft.steps[0].runtime_upload is True
    assert draft.steps[1].input_source.value == "previous_step"
    assert draft.steps[1].input_type.value == "text"
    assert draft.steps[1].output_type.value == "text"
    assert draft.steps[2].output_type.value == "pdf"
    assert compiled.steps[0].output_mode.value == "transcribe_only"
    assert compiled.steps[2].output_type.value == "pdf"
    assert validation.valid


def test_compile_outline_flow_drops_redundant_leading_audio_transcription_step(
    caplog: pytest.LogCaptureFixture,
) -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Audio DOCX report",
            "plan_rationale": "Create a DOCX report from uploaded audio.",
            "steps": [
                {
                    "name": "Transkribera ljud",
                    "task": "Transkribera den uppladdade ljudinspelningen till text.",
                    "model_ref": "default_small_model",
                },
                {
                    "name": "Strukturera innehållet",
                    "task": "Dela transkriptionen i tydliga rubriker.",
                    "output_fields": [
                        {
                            "name": "sections",
                            "field_type": "array",
                            "description": "Rubrikindelat innehåll.",
                            "required": True,
                            "item_fields": [
                                {
                                    "name": "heading",
                                    "field_type": "string",
                                    "description": "Rubrik.",
                                    "required": True,
                                },
                                {
                                    "name": "body",
                                    "field_type": "string",
                                    "description": "Avsnittets text.",
                                    "required": True,
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Skriv dokumenttext",
                    "task": "Skriv ett sammanhängande dokument från rubrikerna.",
                },
            ],
        }
    )
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
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    with caplog.at_level(
        logging.INFO,
        logger="intric.flows.ai_builder.ai_builder_create_outline",
    ):
        draft = compile_outline_to_create_draft(
            outline,
            context=outline_compile_context_from_planning_state(state),
        )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Transcribe audio",
        "Strukturera innehållet",
        "Skriv dokumenttext",
        "Create DOCX",
    ]
    drop_records = [
        record
        for record in caplog.records
        if record.message
        == "ai_builder_redundant_audio_transcription_outline_step_dropped"
    ]
    assert drop_records
    assert getattr(drop_records[0], "step_name") == "Transkribera ljud"
    assert compiled.steps[0].output_mode.value == "transcribe_only"
    assert validation.valid


def test_compile_outline_flow_drops_task_only_audio_to_text_transcription_step(
    caplog: pytest.LogCaptureFixture,
) -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Audio DOCX report",
            "plan_rationale": "Create a DOCX report from uploaded audio.",
            "steps": [
                {
                    "name": "Förbered textunderlag",
                    "task": "Transkribera uppladdade ljudinspelningar till text.",
                },
                {
                    "name": "Strukturera innehållet",
                    "task": "Dela transkriptionen i tydliga rubriker.",
                },
            ],
        }
    )
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
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    with caplog.at_level(
        logging.INFO,
        logger="intric.flows.ai_builder.ai_builder_create_outline",
    ):
        draft = compile_outline_to_create_draft(
            outline,
            context=outline_compile_context_from_planning_state(state),
        )

    assert [step.name for step in draft.steps] == [
        "Transcribe audio",
        "Strukturera innehållet",
        "Create DOCX",
    ]
    assert any(
        record.message
        == "ai_builder_redundant_audio_transcription_outline_step_dropped"
        and getattr(record, "step_name") == "Förbered textunderlag"
        for record in caplog.records
    )


def test_compile_outline_flow_rewrites_structured_audio_transcription_step(
    caplog: pytest.LogCaptureFixture,
) -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Audio DOCX report",
            "plan_rationale": "Create a DOCX report from uploaded audio.",
            "steps": [
                {
                    "name": "Transkribera mötesljud",
                    "task": "Transkribera uppladdade ljudinspelningar till text.",
                    "output_fields": [
                        {
                            "name": "transcript",
                            "field_type": "string",
                            "description": "Sammanställd transkription.",
                            "required": True,
                        },
                        {
                            "name": "segments",
                            "field_type": "array",
                            "description": "Segmenterad transkription.",
                            "required": True,
                            "item_fields": [
                                {
                                    "name": "text",
                                    "field_type": "string",
                                    "description": "Segmenttext.",
                                    "required": True,
                                }
                            ],
                        },
                    ],
                },
                {
                    "name": "Extrahera beslut",
                    "task": "Identifiera beslut och åtgärder från transkriptionen.",
                },
            ],
        }
    )
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
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    with caplog.at_level(
        logging.INFO,
        logger="intric.flows.ai_builder.ai_builder_create_outline",
    ):
        draft = compile_outline_to_create_draft(
            outline,
            context=outline_compile_context_from_planning_state(state),
        )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert draft.steps[1].name == "Strukturera transkription"
    assert "redan transkriberade texten" in draft.steps[1].instructions
    assert "Transkribera mötesljud" not in [step.name for step in draft.steps]
    rewrite_records = [
        record
        for record in caplog.records
        if record.message
        == "ai_builder_redundant_audio_transcription_outline_step_rewritten"
    ]
    assert rewrite_records
    assert validation.valid


def test_compile_outline_flow_audio_to_docx_uses_skeleton_terminal_artifact() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Audio DOCX report",
            "plan_rationale": "Create a DOCX report from uploaded audio.",
            "steps": [
                {
                    "name": "Summarize recording",
                    "task": "Summarize the transcribed audio.",
                }
            ],
        }
    )
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
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Transcribe audio",
        "Summarize recording",
        "Create DOCX",
    ]
    assert [step.input_type.value for step in draft.steps] == [
        "audio",
        "text",
        "text",
    ]
    assert [step.output_type.value for step in draft.steps] == [
        "text",
        "text",
        "docx",
    ]
    assert compiled.steps[0].output_mode.value == "transcribe_only"
    assert compiled.steps[-1].output_type.value == "docx"
    assert validation.valid


def test_compile_outline_audio_docx_keeps_document_body_step_text_when_fields_requested() -> (
    None
):
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Audio DOCX report",
            "plan_rationale": "Create a DOCX report from uploaded audio.",
            "steps": [
                {
                    "name": "Generera DOCX-dokument",
                    "task": "Skapa dokumentets rubriker och textinnehåll.",
                    "output_fields": [
                        {
                            "name": "docx_title",
                            "field_type": "string",
                            "description": "Titel som används i dokumentet.",
                            "required": True,
                        },
                        {
                            "name": "document_sections_count",
                            "field_type": "number",
                            "description": "Antal rubriksektioner som inkluderades.",
                            "required": True,
                        },
                    ],
                }
            ],
        }
    )
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
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Transcribe audio",
        "Generera DOCX-dokument",
        "Create DOCX",
    ]
    assert [step.output_type.value for step in draft.steps] == [
        "text",
        "text",
        "docx",
    ]
    assert draft.steps[1].output_fields is None
    assert compiled.steps[1].output_contract is None
    assert compiled.steps[-1].input_type.value == "text"
    assert compiled.steps[-1].input_bindings is None
    assert validation.valid


@pytest.mark.parametrize("final_output_type", ["docx", "pdf"])
def test_compile_outline_audio_artifact_final_body_step_fans_in_prior_structured_work(
    final_output_type: str,
) -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Audio artifact report",
            "plan_rationale": "Create a document report from uploaded audio.",
            "steps": [
                {
                    "name": "Identifiera och segmentera innehåll per rubrik",
                    "task": "Dela in mötet i rubriker.",
                    "output_fields": [
                        {
                            "name": "sections",
                            "field_type": "object",
                            "description": "Rubrikindelat innehåll.",
                            "required": True,
                            "fields": [
                                {
                                    "name": "introduction",
                                    "field_type": "string",
                                    "description": "Introduktion.",
                                    "required": True,
                                },
                                {
                                    "name": "conclusions",
                                    "field_type": "string",
                                    "description": "Slutsatser.",
                                    "required": True,
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Skapa sammanfattning av allt ovan",
                    "task": "Sammanfatta rubrikavsnitten.",
                    "output_fields": [
                        {
                            "name": "overall_summary",
                            "field_type": "string",
                            "description": "Sammanfattning av hela mötet.",
                            "required": True,
                        }
                    ],
                },
                {
                    "name": "Bygg dokument med rubriker och innehåll",
                    "task": "Skriv dokumentets fullständiga text från alla tidigare steg.",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type=final_output_type,
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    body_step = draft.steps[-2]
    assert body_step.name == "Bygg dokument med rubriker och innehåll"
    assert body_step.input_source.value == "previous_step"
    assert body_step.input_type.value == "json"
    assert body_step.output_type.value == "text"
    assert body_step.uses_previous_fields, (
        "body composer must auto-bind explicit field refs when JSON predecessors exist"
    )
    field_paths = {ref.field_path for ref in body_step.uses_previous_fields}
    assert "sections" in field_paths
    assert "overall_summary" in field_paths
    assert compiled.steps[-2].input_contract is None
    assert draft.steps[-1].output_type.value == final_output_type
    assert validation.valid


def test_compile_outline_audio_docx_four_phase_body_step_fans_in_prior_work() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Audio DOCX report",
            "plan_rationale": "Create a DOCX report from uploaded audio.",
            "steps": [
                {
                    "name": "Rensa transkription",
                    "task": "Normalisera transkriptionen inför analys.",
                },
                {
                    "name": "Identifiera rubrikavsnitt",
                    "task": "Dela in mötet i rubriker.",
                    "output_fields": [
                        {
                            "name": "sections",
                            "field_type": "object",
                            "description": "Rubrikindelat innehåll.",
                            "required": True,
                            "fields": [
                                {
                                    "name": "introduction",
                                    "field_type": "string",
                                    "description": "Introduktion.",
                                    "required": True,
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "Skapa sammanfattning",
                    "task": "Sammanfatta rubrikavsnitten.",
                    "output_fields": [
                        {
                            "name": "overall_summary",
                            "field_type": "string",
                            "description": "Sammanfattning av hela mötet.",
                            "required": True,
                        }
                    ],
                },
                {
                    "name": "Bygg DOCX-dokument",
                    "task": "Skriv dokumentets fullständiga text från alla tidigare steg.",
                },
            ],
        }
    )
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
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    body_step = draft.steps[-2]
    assert body_step.name == "Bygg DOCX-dokument"
    assert body_step.input_source.value == "previous_step"
    assert body_step.input_type.value == "json"
    assert body_step.output_type.value == "text"
    assert body_step.uses_previous_fields, (
        "body composer must auto-bind explicit field refs when JSON predecessors exist"
    )
    field_paths = {ref.field_path for ref in body_step.uses_previous_fields}
    assert "sections" in field_paths
    assert "overall_summary" in field_paths
    transcript_refs = {ref.from_step for ref in body_step.uses_previous_outputs}
    assert transcript_refs, "uses_previous_outputs must include text predecessors"
    assert compiled.steps[-2].input_contract is None
    assert validation.valid


def test_compile_outline_audio_docx_body_step_auto_authors_targeted_refs_when_json_predecessor() -> (
    None
):
    """When the audio→DOCX skeleton produces a body composer text step with
    JSON predecessors, the dataflow normalizer must switch input_source to
    `previous_step` and auto-populate `uses_previous_fields` so the
    `prefer_targeted_underlag_over_all_previous_steps` semantic invariant
    does not fire and the LLM is not stuck in a repair loop it cannot fix.
    """
    from intric.flows.ai_builder.ai_builder_critic_invariants import (
        CRITIC_INVARIANTS,
        CriticContext,
        evaluate_critic_invariants,
    )
    from intric.flows.ai_builder.ai_builder_framework_policy import (
        OutputIntentResolution,
    )
    from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
        PlannerPatternSignals,
    )

    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Mötesrapport från ljud till Word",
            "plan_rationale": "Transkribera ljud och skapa DOCX-rapport.",
            "steps": [
                {
                    "name": "Identifiera mötesmetadata",
                    "task": "Identifiera deltagare och datum från transkriptionen.",
                    "output_fields": [
                        {
                            "name": "meeting_title",
                            "field_type": "string",
                            "description": "Mötestitel.",
                            "required": True,
                        },
                        {
                            "name": "participants",
                            "field_type": "string",
                            "description": "Deltagare.",
                            "required": True,
                        },
                    ],
                },
                {
                    "name": "Identifiera beslut",
                    "task": "Lista alla beslut.",
                    "output_fields": [
                        {
                            "name": "decisions_summary",
                            "field_type": "string",
                            "description": "Beslut sammanfattat.",
                            "required": True,
                        }
                    ],
                },
                {
                    "name": "Skriv strukturerad rapport",
                    "task": "Skriv en strukturerad mötesrapport på svenska.",
                },
            ],
        }
    )
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
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    body_step = draft.steps[-2]
    assert body_step.name == "Skriv strukturerad rapport"
    assert body_step.output_type.value == "text"
    assert body_step.input_source.value == "previous_step"
    assert body_step.input_type.value == "json"
    assert body_step.uses_previous_fields, (
        "body step must auto-bind uses_previous_fields when JSON predecessors exist"
    )
    field_paths = {ref.field_path for ref in body_step.uses_previous_fields}
    assert "meeting_title" in field_paths
    assert "decisions_summary" in field_paths

    composer = compiled.steps[-2]
    assert composer.input_bindings is not None
    question = composer.input_bindings["question"]
    assert "step_" in question and "output.structured" in question

    context = CriticContext(
        spec=compiled,
        flow=None,
        answer_signals={},
        text="",
        requirements_text="",
        signal_text="",
        planner_patterns=PlannerPatternSignals(),
        output_intent=OutputIntentResolution(terminal_output="docx_document"),
        mixed_audio_doc_input=False,
    )
    issues = evaluate_critic_invariants(context, invariants=CRITIC_INVARIANTS)
    issue_ids = [issue.id for issue in issues]
    assert "prefer_targeted_underlag_over_all_previous_steps" not in issue_ids, (
        f"prefer_targeted_underlag must not fire after auto-binding; issues={issue_ids}"
    )
    assert validation.valid


def test_auto_bind_targeted_underlag_skips_when_aggregation_intent_is_aggregate() -> (
    None
):
    """Aggregation intents `aggregate` and `compare` retain `all_previous_steps`
    because the multi-document compare invariant requires it. Auto-binding
    must defer to that wider rule.
    """
    from intric.flows.ai_builder.ai_builder_create_dataflow import (
        auto_bind_targeted_underlag_for_text_composer,
    )
    from intric.flows.ai_builder.ai_builder_new_step_models import NewStepDraft

    steps_before = [
        NewStepDraft(
            name="Sektion A",
            instructions="x",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            output_fields=[_field("section_a", "string", description="Sektion A.")],
        ),
        NewStepDraft(
            name="Sektion B",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            output_fields=[_field("section_b", "string", description="Sektion B.")],
        ),
        NewStepDraft(
            name="Aggregera",
            instructions="x",
            input_source="all_previous_steps",
            input_type="text",
            output_type="text",
        ),
    ]

    for intent in ("aggregate", "compare"):
        result = auto_bind_targeted_underlag_for_text_composer(
            steps_before,
            aggregation_intent=cast(AggregationIntent, intent),
        )
        assert result is steps_before, (
            f"intent={intent!r} should be a no-op, but the composer was rewritten"
        )
        composer = result[2]
        assert composer.input_source.value == "all_previous_steps"
        assert composer.uses_previous_fields == []


def test_auto_bind_targeted_underlag_two_step_linear_flow_is_unchanged() -> None:
    """A 2-step `flow_input → text_summary` flow with linear intent must NOT
    be rewritten. The skeleton already defaults the terminal to
    `previous_step` for linear shapes, so auto-bind has nothing to do.
    Reviewer concern: a 2-step shape with `composer_index == 1` and a JSON
    predecessor could otherwise force `uses_previous_fields` even when user
    intent is "summarize what came before" via broad fan-in.
    """
    from intric.flows.ai_builder.ai_builder_create_dataflow import (
        auto_bind_targeted_underlag_for_text_composer,
    )
    from intric.flows.ai_builder.ai_builder_new_step_models import NewStepDraft

    steps_before = [
        NewStepDraft(
            name="Hämta data",
            instructions="x",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            output_fields=[_field("payload", "string", description="API-svar.")],
        ),
        NewStepDraft(
            name="Skriv kommentar",
            instructions="x",
            input_source="previous_step",
            input_type="text",
            output_type="text",
        ),
    ]

    result = auto_bind_targeted_underlag_for_text_composer(
        steps_before,
        aggregation_intent="linear",
    )
    assert result is steps_before, "2-step linear flow must be a no-op"
    composer = result[1]
    assert composer.input_source.value == "previous_step"
    assert composer.uses_previous_fields == []
    assert composer.uses_previous_outputs == []


def test_auto_bind_targeted_underlag_skips_when_text_priors_exceed_soft_cap() -> None:
    # Pins 78bf7994: the soft cap counts text priors, not JSON priors.
    from intric.flows.ai_builder.ai_builder_create_dataflow import (
        auto_bind_targeted_underlag_for_text_composer,
    )
    from intric.flows.ai_builder.ai_builder_critic_invariants import (
        TARGETED_UNDERLAG_SOFT_CAP,
    )
    from intric.flows.ai_builder.ai_builder_new_step_models import NewStepDraft

    text_priors: list[NewStepDraft] = []
    for index in range(TARGETED_UNDERLAG_SOFT_CAP + 1):
        text_priors.append(
            NewStepDraft(
                name=f"Skriv del {index}",
                instructions="x",
                input_source="flow_input" if index == 0 else "previous_step",
                input_type="text",
                output_type="text",
            )
        )
    json_anchor = NewStepDraft(
        name="Extrahera fakta",
        instructions="x",
        input_source="previous_step",
        input_type="text",
        output_type="json",
        output_fields=[_field("summary", "string")],
    )
    composer = NewStepDraft(
        name="Slutrapport",
        instructions="x",
        input_source="all_previous_steps",
        input_type="text",
        output_type="text",
    )
    steps_before = [*text_priors, json_anchor, composer]

    result = auto_bind_targeted_underlag_for_text_composer(
        steps_before,
        aggregation_intent="linear",
    )
    assert result is steps_before, "over-cap text priors should bail out"
    assert result[-1].input_source.value == "all_previous_steps"


def test_auto_bind_targeted_underlag_fires_when_many_json_priors_with_few_text_priors() -> (
    None
):
    # Pins 78bf7994: many JSON priors should still auto-bind targeted refs.
    from intric.flows.ai_builder.ai_builder_create_dataflow import (
        auto_bind_targeted_underlag_for_text_composer,
    )
    from intric.flows.ai_builder.ai_builder_critic_invariants import (
        TARGETED_UNDERLAG_SOFT_CAP,
    )
    from intric.flows.ai_builder.ai_builder_new_step_models import NewStepDraft

    transcription = NewStepDraft(
        name="Transkribera ljudet",
        instructions="x",
        input_source="flow_input",
        input_type="audio",
        output_type="text",
    )
    json_extractions: list[NewStepDraft] = []
    for index in range(TARGETED_UNDERLAG_SOFT_CAP + 2):
        json_extractions.append(
            NewStepDraft(
                name=f"Extrahera del {index}",
                instructions="x",
                input_source="previous_step",
                input_type="json" if index > 0 else "text",
                output_type="json",
                output_fields=[
                    _field(f"section_{index}", "string", description=f"Del {index}.")
                ],
            )
        )
    composer = NewStepDraft(
        name="Skriv sammanfattning",
        instructions="x",
        input_source="previous_step",
        input_type="json",
        output_type="text",
    )
    steps_before = [transcription, *json_extractions, composer]

    result = auto_bind_targeted_underlag_for_text_composer(
        steps_before,
        aggregation_intent="linear",
    )

    assert result is not steps_before, (
        "auto-binder must fire when bulk of priors is JSON+output_fields, "
        "even if total prior count exceeds the text-prior cap"
    )
    rewritten_composer = result[-1]
    assert rewritten_composer.input_source.value == "previous_step"
    assert len(rewritten_composer.uses_previous_fields) == len(json_extractions), (
        "every JSON predecessor's structured field must be referenced"
    )
    referenced_steps = {
        ref.from_step for ref in rewritten_composer.uses_previous_fields
    }
    assert referenced_steps == {index + 2 for index in range(len(json_extractions))}, (
        "field refs must point at every JSON predecessor by 1-indexed position"
    )
    assert any(
        ref.from_step == 1 for ref in rewritten_composer.uses_previous_outputs
    ), "the transcription text prior must be wired via uses_previous_outputs"


def test_auto_bind_targeted_underlag_rewrites_previous_step_composer_with_multiple_json_priors() -> (
    None
):
    """When the final text composer reads from `previous_step` and at least
    two prior content steps emit JSON with output_fields, auto-bind must
    populate `uses_previous_fields` with refs across all JSON priors. The
    composer keeps `previous_step` as its source — the goal is targeted
    fan-in, not concatenated body text. The 1-JSON-prior linear case
    remains a no-op (pinned by
    `test_auto_bind_targeted_underlag_two_step_linear_flow_is_unchanged`).
    """
    from intric.flows.ai_builder.ai_builder_create_dataflow import (
        auto_bind_targeted_underlag_for_text_composer,
    )
    from intric.flows.ai_builder.ai_builder_new_step_models import NewStepDraft

    steps_before = [
        NewStepDraft(
            name="Extrahera produktdata",
            instructions="x",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            output_fields=[
                _field("product_name", "string", description="Produktnamn."),
                _field("product_price", "string", description="Produktpris."),
            ],
        ),
        NewStepDraft(
            name="Extrahera kunddata",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            output_fields=[
                _field("customer_segment", "string", description="Kundsegment."),
            ],
        ),
        NewStepDraft(
            name="Extrahera leveransdata",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="json",
            output_fields=[
                _field("delivery_window", "string", description="Leveransfönster."),
            ],
        ),
        NewStepDraft(
            name="Skriv sammanfattning",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="text",
        ),
    ]

    result = auto_bind_targeted_underlag_for_text_composer(
        steps_before,
        aggregation_intent="linear",
    )

    assert result is not steps_before, (
        "composer with previous_step source and ≥2 JSON priors must be rewritten"
    )
    composer = result[-1]
    assert composer.input_source.value == "previous_step", (
        "input_source should remain previous_step (targeted fan-in, not concat)"
    )

    field_refs = {
        (ref.from_step, ref.field_path) for ref in composer.uses_previous_fields
    }
    assert (1, "product_name") in field_refs
    assert (1, "product_price") in field_refs
    assert (2, "customer_segment") in field_refs
    assert (3, "delivery_window") in field_refs
    assert len(field_refs) == 4, (
        f"expected 4 field refs across 3 JSON priors, got {len(field_refs)}"
    )


def test_auto_bind_targeted_underlag_skips_previous_step_composer_with_single_json_prior() -> (
    None
):
    """A composer reading `previous_step` from exactly one JSON prior is a
    valid linear extract→summarize pipeline. Auto-bind must NOT inflate it
    with multi-source attachment (Codex's "no eager bind" risk).
    """
    from intric.flows.ai_builder.ai_builder_create_dataflow import (
        auto_bind_targeted_underlag_for_text_composer,
    )
    from intric.flows.ai_builder.ai_builder_new_step_models import NewStepDraft

    steps_before = [
        NewStepDraft(
            name="Extrahera fält",
            instructions="x",
            input_source="flow_input",
            input_type="text",
            output_type="json",
            output_fields=[
                _field("payload", "string", description="Extraherad data."),
            ],
        ),
        NewStepDraft(
            name="Skriv kommentar",
            instructions="x",
            input_source="previous_step",
            input_type="json",
            output_type="text",
        ),
    ]

    result = auto_bind_targeted_underlag_for_text_composer(
        steps_before,
        aggregation_intent="linear",
    )

    assert result is steps_before, (
        "single-JSON-prior + previous_step composer must remain a no-op"
    )
    composer = result[-1]
    assert composer.input_source.value == "previous_step"
    assert composer.uses_previous_fields == []


def test_compile_outline_audio_docx_protocol_step_keeps_transcript_underlag() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Mötesprotokoll från ljud till Word",
            "plan_rationale": "Transkribera ljud och skapa DOCX-protokoll.",
            "steps": [
                {
                    "name": "Strukturera transkription",
                    "task": "Strukturera den redan transkriberade texten.",
                    "output_fields": [
                        {
                            "name": "transcription_text",
                            "field_type": "string",
                            "description": "Fullständig transkription.",
                            "required": True,
                        },
                        {
                            "name": "speaker_turns",
                            "field_type": "array",
                            "description": "Talarsegment i ordning.",
                            "required": False,
                            "item_fields": [
                                {
                                    "name": "segment_text",
                                    "field_type": "string",
                                    "description": "Text för segmentet.",
                                    "required": True,
                                }
                            ],
                        },
                    ],
                },
                {
                    "name": "Identifiera mötesmetadata",
                    "task": "Identifiera titel, organisation och sekreterare.",
                    "output_fields": [
                        {
                            "name": "meeting_title",
                            "field_type": "string",
                            "description": "Mötestitel.",
                            "required": True,
                        },
                        {
                            "name": "organization_name",
                            "field_type": "string",
                            "description": "Organisation.",
                            "required": True,
                        },
                    ],
                },
                {
                    "name": "Skapa mötesprotokoll med fasta rubriker",
                    "task": "Skapa protokollsektioner från metadata och transkription.",
                    "output_fields": [
                        {
                            "name": "protocol_sections",
                            "field_type": "object",
                            "description": "Innehåll per rubrik.",
                            "required": True,
                            "fields": [
                                {
                                    "name": "Sammanfattning",
                                    "field_type": "string",
                                    "description": "Sammanfattning.",
                                    "required": True,
                                },
                                {
                                    "name": "Diskussion",
                                    "field_type": "string",
                                    "description": "Diskussion.",
                                    "required": True,
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "Förbered DOCX-innehåll",
                    "task": "Skriv dokumentets fullständiga text från tidigare steg.",
                },
            ],
        }
    )
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
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state, ui_language="sv"),
    )
    normalized = normalize_create_draft_mechanics(draft)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    metadata_step = normalized.steps[2]
    assert metadata_step.input_type.value == "text"
    assert [
        (ref.from_step, ref.label) for ref in metadata_step.uses_previous_outputs
    ] == [(1, "Källmaterial")]
    assert compiled.steps[2].input_bindings is not None
    assert compiled.steps[2].input_bindings["question"] == (
        "{{ step_b.output.structured }}\n\nKällmaterial: {{ step_a.output.text }}"
    )

    protocol_step = normalized.steps[3]
    assert protocol_step.name == "Skapa mötesprotokoll med fasta rubriker"
    assert protocol_step.input_source.value == "previous_step"
    assert protocol_step.input_type.value == "text"
    assert protocol_step.uses_previous_fields == []
    assert [
        (ref.from_step, ref.label) for ref in protocol_step.uses_previous_outputs
    ] == [(1, "Källmaterial")]

    compiled_protocol_step = compiled.steps[3]
    assert compiled_protocol_step.input_bindings is not None
    assert compiled_protocol_step.input_bindings["question"] == (
        "{{ step_c.output.structured }}\n\nKällmaterial: {{ step_a.output.text }}"
    )
    assert validation.valid


def test_compile_create_draft_direct_audio_docx_bad_shape_gets_source_underlag() -> (
    None
):
    draft = FlowCreateDraft(
        flow_name="Mötesprotokoll från ljud till Word",
        plan_rationale="Transkribera ljud och skapa DOCX.",
        steps=[
            CreateStepDraft(
                name="Transkribera ljud",
                instructions="Transkribera uppladdat ljud.",
                input_source="flow_input",
                input_type="audio",
                output_type="text",
                runtime_upload=True,
                runtime_required=True,
            ),
            CreateStepDraft(
                name="Strukturera transkription",
                instructions="Strukturera transkriptionen.",
                input_source="previous_step",
                input_type="text",
                output_type="json",
                output_fields=[_field("transcription_text", "string")],
            ),
            CreateStepDraft(
                name="Identifiera mötesmetadata",
                instructions="Identifiera mötestitel.",
                input_source="previous_step",
                input_type="json",
                output_type="json",
                output_fields=[_field("meeting_title", "string")],
            ),
            CreateStepDraft(
                name="Skapa mötesprotokoll med fasta rubriker",
                instructions="Skapa protokollsektioner från metadata och transkription.",
                input_source="previous_step",
                input_type="json",
                output_type="json",
                output_fields=[_field("protocol_sections", "string")],
            ),
            CreateStepDraft(
                name="Skapa DOCX",
                instructions="Skapa slutdokumentet.",
                input_source="previous_step",
                input_type="json",
                output_type="docx",
                document_delivery_mode="generated",
            ),
        ],
    )

    compiled = compile_create_draft(draft)

    metadata_question = compiled.steps[2].input_bindings["question"]
    protocol_question = compiled.steps[3].input_bindings["question"]
    docx_question = compiled.steps[4].input_bindings["question"]
    assert compiled.steps[2].input_type.value == "text"
    assert compiled.steps[2].input_contract is None
    assert compiled.steps[3].input_type.value == "text"
    assert compiled.steps[3].input_contract is None
    assert compiled.steps[4].input_type.value == "text"
    assert compiled.steps[4].input_contract is None
    assert metadata_question == (
        "{{ step_b.output.structured }}\n\nKällmaterial: {{ step_a.output.text }}"
    )
    assert protocol_question == (
        "{{ step_c.output.structured }}\n\nKällmaterial: {{ step_a.output.text }}"
    )
    assert docx_question == (
        "{{ step_d.output.structured }}\n\nKällmaterial: {{ step_a.output.text }}"
    )
    assert validate_spec(compiled).valid


def test_compile_create_draft_audio_report_section_extractors_keep_transcript_underlag() -> (
    None
):
    draft = FlowCreateDraft(
        flow_name="Mötesrapport från ljud",
        plan_rationale="Transkribera ljud och skapa en strukturerad mötesrapport.",
        steps=[
            CreateStepDraft(
                name="Transkribera mötesljud",
                instructions="Transkribera mötesljudet till svensk text.",
                input_source="flow_input",
                input_type="audio",
                output_type="text",
                runtime_upload=True,
                runtime_required=True,
            ),
            CreateStepDraft(
                name="Etablera möteskontext",
                instructions="Skapa möteskontext baserat på transkriberingen.",
                input_source="previous_step",
                input_type="text",
                output_type="json",
                output_fields=[_field("meeting_context", "string")],
            ),
            CreateStepDraft(
                name="Analysera bakgrund",
                instructions="Läs hela transkriberingen och extrahera bakgrund.",
                input_source="previous_step",
                input_type="json",
                output_type="json",
                output_fields=[_field("background_notes", "string")],
            ),
            CreateStepDraft(
                name="Analysera genomgång och diskussion",
                instructions=(
                    "Läs hela transkriberingen och extrahera diskussionsunderlag."
                ),
                input_source="previous_step",
                input_type="json",
                output_type="json",
                output_fields=[_field("discussion_notes", "string")],
            ),
            CreateStepDraft(
                name="Skriv fullständig mötesrapport",
                instructions="Skriv rapporten från möteskontext och alla underlag.",
                input_source="previous_step",
                input_type="json",
                output_type="json",
                output_fields=[_field("report_text", "string")],
            ),
            CreateStepDraft(
                name="Skapa DOCX",
                instructions="Skapa slutdokumentet.",
                input_source="previous_step",
                input_type="json",
                output_type="docx",
                document_delivery_mode="generated",
            ),
        ],
    )

    compiled = compile_create_draft(draft)

    for step_index in (2, 3, 4, 5):
        step = compiled.steps[step_index]
        assert step.input_type.value == "text"
        assert step.input_contract is None
        assert step.input_bindings is not None
        question = step.input_bindings["question"]
        assert "Källmaterial: {{ step_a.output.text }}" in question
    assert (
        "{{ step_b.output.structured }}" in compiled.steps[2].input_bindings["question"]
    )
    assert (
        "{{ step_c.output.structured }}" in compiled.steps[3].input_bindings["question"]
    )
    assert (
        "{{ step_d.output.structured }}" in compiled.steps[4].input_bindings["question"]
    )
    assert (
        "{{ step_e.output.structured }}" in compiled.steps[5].input_bindings["question"]
    )
    assert validate_spec(compiled).valid


def test_compile_create_draft_text_report_keeps_source_and_structured_underlag() -> (
    None
):
    draft = FlowCreateDraft(
        flow_name="Mötesrapport från ljud",
        plan_rationale="Transkribera ljud och skapa en textbaserad mötesrapport.",
        steps=[
            CreateStepDraft(
                name="Transkribera mötesljud",
                instructions="Transkribera mötesljudet till svensk text.",
                input_source="flow_input",
                input_type="audio",
                output_type="text",
                runtime_upload=True,
                runtime_required=True,
            ),
            CreateStepDraft(
                name="Etablera möteskontext",
                instructions="Skapa möteskontext baserat på transkriberingen.",
                input_source="previous_step",
                input_type="text",
                output_type="json",
                output_fields=[_field("meeting_context", "string")],
            ),
            CreateStepDraft(
                name="Analysera beslut",
                instructions="Extrahera beslut från mötet.",
                input_source="previous_step",
                input_type="json",
                output_type="json",
                output_fields=[_field("decisions", "string")],
            ),
            CreateStepDraft(
                name="Skriv rapport",
                instructions="Skriv en textbaserad rapport från underlaget.",
                input_source="previous_step",
                input_type="json",
                output_type="text",
            ),
        ],
    )

    compiled = compile_create_draft(draft)

    analysis_step = compiled.steps[2]
    report_step = compiled.steps[3]
    assert analysis_step.input_type.value == "text"
    assert analysis_step.input_contract is None
    assert analysis_step.input_bindings == {
        "question": (
            "{{ step_b.output.structured }}\n\nKällmaterial: {{ step_a.output.text }}"
        )
    }
    assert report_step.input_type.value == "text"
    assert report_step.input_contract is None
    assert report_step.input_bindings == {
        "question": (
            "{{ step_c.output.structured }}\n\nKällmaterial: {{ step_a.output.text }}"
        )
    }
    assert validate_spec(compiled).valid


def test_compile_outline_audio_pdf_protocol_step_auto_authors_targeted_underlag() -> (
    None
):
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Mötesprotokoll från ljud till PDF",
            "plan_rationale": "Transkribera ljud och skapa PDF-protokoll.",
            "steps": [
                {
                    "name": "Strukturera transkription",
                    "task": "Strukturera den redan transkriberade texten.",
                    "output_fields": [
                        {
                            "name": "transcription_text",
                            "field_type": "string",
                            "description": "Fullständig transkription.",
                            "required": True,
                        },
                    ],
                },
                {
                    "name": "Identifiera mötesmetadata",
                    "task": "Identifiera titel, organisation och sekreterare.",
                    "output_fields": [
                        {
                            "name": "meeting_title",
                            "field_type": "string",
                            "description": "Mötestitel.",
                            "required": True,
                        },
                    ],
                },
                {
                    "name": "Skapa mötesprotokoll med fasta rubriker",
                    "task": "Skapa protokollsektioner från metadata och transkription.",
                    "output_fields": [
                        {
                            "name": "protocol_sections",
                            "field_type": "object",
                            "description": "Innehåll per rubrik.",
                            "required": True,
                            "fields": [
                                {
                                    "name": "Sammanfattning",
                                    "field_type": "string",
                                    "description": "Sammanfattning.",
                                    "required": True,
                                },
                            ],
                        }
                    ],
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="pdf",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state, ui_language="sv"),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    protocol_step = draft.steps[3]
    assert protocol_step.input_source.value == "previous_step"
    assert protocol_step.input_type.value == "json"
    assert protocol_step.output_type.value == "text"
    field_paths = {ref.field_path for ref in protocol_step.uses_previous_fields}
    assert "transcription_text" in field_paths
    assert "meeting_title" in field_paths
    assert compiled.steps[3].input_bindings is not None
    assert "output.structured" in compiled.steps[3].input_bindings["question"]
    assert validation.valid


@pytest.mark.parametrize("final_output_type", ["docx", "pdf"])
def test_compile_outline_audio_document_without_pattern_still_creates_transcript_source(
    final_output_type: str,
) -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Mötesrapport från ljud",
            "plan_rationale": "Analysera transkriberat ljud och skapa rapport.",
            "runtime_input": {"input_type": "audio", "required": True},
            "final_output_type": final_output_type,
            "steps": [
                {
                    "name": "Etablera gemensam möteskontext",
                    "task": "Läs hela den transkriberade mötestexten.",
                    "output_fields": [
                        {
                            "name": "meeting_context",
                            "field_type": "object",
                            "description": "Gemensam möteskontext.",
                            "required": True,
                            "fields": [
                                {
                                    "name": "meeting_type",
                                    "field_type": "string",
                                    "description": "Mötestyp.",
                                    "required": True,
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "Analysera bakgrund",
                    "task": "Analysera hela transkriberingen med fokus på bakgrund.",
                    "output_fields": [
                        {
                            "name": "background_points",
                            "field_type": "array",
                            "description": "Bakgrundspunkter.",
                            "required": True,
                            "item_fields": [
                                {
                                    "name": "point",
                                    "field_type": "string",
                                    "description": "Bakgrundspunkt.",
                                    "required": True,
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "Skriv strukturerad mötesrapport",
                    "task": (
                        "Skriv en fullständig strukturerad mötesrapport på svenska "
                        "utifrån allt ackumulerat analysunderlag."
                    ),
                },
            ],
        }
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=OutlineCompileContext(ui_language="sv"),
    )
    normalized = normalize_create_draft_mechanics(draft)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [
        (step.input_source.value, step.input_type.value, step.output_type.value)
        for step in normalized.steps
    ] == [
        ("flow_input", "audio", "text"),
        ("previous_step", "text", "json"),
        ("previous_step", "text", "json"),
        ("previous_step", "json", "text"),
        ("previous_step", "text", final_output_type),
    ]
    assert [step.name for step in draft.steps[:4]] == [
        "Transkribera ljud",
        "Etablera gemensam möteskontext",
        "Analysera bakgrund",
        "Skriv strukturerad mötesrapport",
    ]
    assert compiled.steps[0].output_mode == OutputMode.TRANSCRIBE_ONLY
    assert not any(
        step.input_source == InputSource.FLOW_INPUT
        and step.input_type == InputType.AUDIO
        and step.output_type == OutputType.JSON
        for step in compiled.steps
    )
    assert compiled.steps[2].input_bindings == {
        "question": "{{ step_b.output.structured }}\n\nKällmaterial: {{ step_a.output.text }}"
    }
    assert compiled.steps[3].input_source == InputSource.PREVIOUS_STEP
    body_field_paths = {
        ref.field_path for ref in normalized.steps[3].uses_previous_fields
    }
    assert "meeting_context" in body_field_paths
    assert "background_points" in body_field_paths
    assert compiled.steps[3].input_bindings is not None
    assert "output.structured" in compiled.steps[3].input_bindings["question"]
    assert compiled.steps[4].input_source == InputSource.PREVIOUS_STEP
    assert validation.valid


def test_compile_outline_audio_document_json_hint_keeps_transcript_source() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Mötesrapport från ljud",
            "plan_rationale": "Transkribera ljud och skapa rapport.",
            "runtime_input": {"input_type": "audio", "required": True},
            "final_output_type": "pdf",
            "steps": [
                {
                    "name": "Transkribera ljud",
                    "task": "Transkribera uppladdat mötesljud till text.",
                    "output_type": "json",
                },
                {
                    "name": "Skriv rapport",
                    "task": "Skriv en rapport från transkriberingen.",
                },
            ],
        }
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=OutlineCompileContext(ui_language="sv"),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert compiled.steps[0].input_source == InputSource.FLOW_INPUT
    assert compiled.steps[0].input_type == InputType.AUDIO
    assert compiled.steps[0].output_type == OutputType.TEXT
    assert compiled.steps[0].output_mode == OutputMode.TRANSCRIBE_ONLY
    assert not any(
        step.input_source == InputSource.FLOW_INPUT
        and step.input_type == InputType.AUDIO
        and step.output_type == OutputType.JSON
        for step in compiled.steps
    )
    assert compiled.steps[2].input_bindings == {
        "question": "{{ step_b.output.structured }}\n\nKällmaterial: {{ step_a.output.text }}"
    }
    assert validation.valid


def test_compile_outline_wraps_skeleton_materialization_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Broken skeleton",
            "plan_rationale": "Compile a broken skeleton.",
            "steps": [{"name": "Analyze", "task": "Analyze the input."}],
        }
    )

    def _raise_value_error(**_kwargs: object) -> None:
        raise ValueError("invalid skeleton tuple")

    monkeypatch.setattr(
        "intric.flows.ai_builder.ai_builder_create_outline.materialize_step_skeleton",
        _raise_value_error,
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        compile_outline_to_create_draft(outline)

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.detail == "invalid skeleton tuple"
    assert exc_info.value.log_context["runtime_input_type"] == "text"
    assert exc_info.value.log_context["final_output_type"] == "text"
    assert exc_info.value.log_context["semantic_step_count"] == 1


def test_compile_outline_flow_audio_artifact_aggregate_fan_in_lands_on_terminal() -> (
    None
):
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Aggregate audio report",
            "plan_rationale": "Aggregate several analyses into one PDF.",
            "steps": [
                {"name": "Extract themes", "task": "Extract main themes."},
                {"name": "Assess risks", "task": "Assess risks in the recording."},
                {"name": "Synthesize", "task": "Synthesize all prior work."},
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="pdf",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
            aggregation_intent="aggregate",
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Transcribe audio",
        "Extract themes",
        "Assess risks",
        "Synthesize",
        "Create PDF",
    ]
    assert draft.steps[-1].input_source.value == "all_previous_steps"
    assert draft.steps[-1].input_type.value == "text"
    assert compiled.steps[-1].input_bindings is None
    assert validation.valid


def test_compile_outline_flow_keeps_text_artifact_step_after_audio_transcription() -> (
    None
):
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Audio text report",
            "plan_rationale": "Create a readable report from uploaded audio.",
            "steps": [
                {
                    "name": "Write report",
                    "task": "Write a concise report from the transcribed audio.",
                    "output_type": "text",
                }
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="text",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Transcribe audio",
        "Write report",
    ]
    assert draft.steps[0].input_type.value == "audio"
    assert draft.steps[0].runtime_upload is True
    assert draft.steps[1].input_source.value == "previous_step"
    assert compiled.steps[0].output_mode.value == "transcribe_only"
    assert compiled.steps[1].output_mode.value == "pass_through"
    assert validation.valid


def test_outline_compile_context_reads_pattern_chain_from_architecture_commit() -> None:
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="pdf",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["audio_to_artifact_report"],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    context = outline_compile_context_from_planning_state(state)

    assert context is not None
    assert context.pattern_ids == ("audio_to_artifact_report",)
    assert context.pattern_chain_steps == (
        FLOW_INPUT_AUDIO_TRANSCRIPTION,
        TERMINAL_ARTIFACT_STEP,
    )


def test_outline_compile_context_preserves_compiled_chain_and_semantic_patterns() -> (
    None
):
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="pdf",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=[
                "multi_step_quality_chain",
                "form_field_runtime_inputs",
            ],
            required_capabilities=["input_document", "output_mode_pass_through"],
        )
    )

    context = outline_compile_context_from_planning_state(state)

    assert context is not None
    assert set(context.pattern_ids) == {
        "form_field_runtime_inputs",
        "multi_step_quality_chain",
    }
    assert STRUCTURED_EXTRACTION_STEP in context.pattern_chain_steps
    assert TERMINAL_ARTIFACT_STEP in context.pattern_chain_steps


def test_compile_outline_flow_realizes_docx_template_chain_from_pattern() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Template report",
            "plan_rationale": "Fill a DOCX template from uploaded material.",
            "steps": [
                {
                    "name": "Prepare report content",
                    "task": "Prepare the content that should be placed in the template.",
                }
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="docx",
                    output_mode="template_fill",
                )
            ],
            chosen_patterns=["document_to_docx_template"],
            required_capabilities=["input_document", "output_mode_template_fill"],
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Extract template variables",
        "Prepare report content",
        "Fill DOCX template",
    ]
    assert [step.output_type.value for step in draft.steps] == [
        "json",
        "text",
        "docx",
    ]
    assert draft.steps[0].runtime_upload is True
    assert draft.steps[2].document_delivery_mode == "template_fill"
    assert compiled.steps[2].output_mode.value == "template_fill"
    assert validation.valid


def test_compile_outline_flow_docx_chain_preserves_all_semantic_steps() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Template report",
            "plan_rationale": "Fill a DOCX template from uploaded material.",
            "steps": [
                {
                    "name": "Extract findings",
                    "task": "Extract the findings that matter for the report.",
                },
                {
                    "name": "Write narrative",
                    "task": "Write the narrative content for the template.",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="docx",
                    output_mode="template_fill",
                )
            ],
            chosen_patterns=["document_to_docx_template"],
            required_capabilities=["input_document", "output_mode_template_fill"],
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Extract template variables",
        "Extract findings",
        "Write narrative",
        "Fill DOCX template",
    ]
    assert compiled.steps[-1].output_mode.value == "template_fill"
    assert validation.valid


def test_compile_outline_template_fill_places_fan_in_on_synthesis_step() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Template comparison report",
            "plan_rationale": "Compare uploaded material before filling the template.",
            "steps": [
                {
                    "name": "Extract findings",
                    "task": "Extract findings from the uploaded material.",
                },
                {
                    "name": "Write synthesis",
                    "task": "Compare all prior work and write the report narrative.",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="docx",
                    output_mode="template_fill",
                )
            ],
            chosen_patterns=["document_to_docx_template"],
            required_capabilities=["input_document", "output_mode_template_fill"],
            aggregation_intent="compare",
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Extract template variables",
        "Extract findings",
        "Write synthesis",
        "Fill DOCX template",
    ]
    assert draft.steps[-2].input_source.value == "all_previous_steps"
    assert compiled.steps[-2].input_bindings is None
    assert draft.steps[-1].input_source.value == "previous_step"
    assert draft.steps[-1].document_delivery_mode == "template_fill"
    assert validation.valid


def test_compile_outline_flow_docx_chain_still_wraps_rich_template_outline() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Template report",
            "plan_rationale": "Fill a DOCX template from several phases.",
            "steps": [
                {
                    "name": f"Prepare section {index}",
                    "task": f"Prepare section {index} for the template.",
                }
                for index in range(1, 6)
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="docx",
                    output_mode="template_fill",
                )
            ],
            chosen_patterns=["document_to_docx_template"],
            required_capabilities=["input_document", "output_mode_template_fill"],
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Extract template variables",
        "Prepare section 1",
        "Prepare section 2",
        "Prepare section 3",
        "Prepare section 4",
        "Prepare section 5",
        "Fill DOCX template",
    ]
    assert compiled.steps[-1].output_mode.value == "template_fill"
    assert validation.valid


def test_compile_outline_flow_uses_committed_template_fill_mode_without_pattern() -> (
    None
):
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Template report",
            "plan_rationale": "Fill a DOCX template from uploaded material.",
            "steps": [
                {
                    "name": "Prepare report",
                    "task": "Prepare the report content for the template.",
                }
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="docx",
                    output_mode="template_fill",
                )
            ],
            chosen_patterns=[],
            required_capabilities=["input_document", "output_mode_template_fill"],
        )
    )

    context = outline_compile_context_from_planning_state(state)
    draft = compile_outline_to_create_draft(outline, context=context)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert context is not None
    assert context.final_output_mode is not None
    assert context.final_output_mode.value == "template_fill"
    assert [step.name for step in draft.steps] == [
        "Extract template variables",
        "Prepare report",
        "Fill DOCX template",
    ]
    assert draft.steps[-1].document_delivery_mode == "template_fill"
    assert compiled.steps[-1].output_mode.value == "template_fill"
    assert validation.valid


def test_compile_outline_flow_realizes_structured_quality_chain_from_pattern() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Structured report",
            "plan_rationale": "Analyze uploaded material and produce a final PDF.",
            "steps": [
                {
                    "name": "Analyze material",
                    "task": "Analyze the uploaded material and produce the requested report.",
                }
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="pdf",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["multi_step_quality_chain"],
            required_capabilities=["input_document", "output_mode_pass_through"],
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Extract structured foundation",
        "Analyze material",
        "Review quality and gaps",
        "Create PDF",
    ]
    assert [step.output_type.value for step in draft.steps] == [
        "json",
        "text",
        "text",
        "pdf",
    ]
    assert draft.steps[0].runtime_upload is True
    assert draft.steps[0].output_fields is not None
    assert compiled.steps[1].input_type.value == "json"
    assert compiled.steps[3].output_type.value == "pdf"
    assert validation.valid


def test_compile_outline_flow_localizes_server_owned_final_step_name() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Riskanalys",
            "plan_rationale": "Analysera uppladdade dokument.",
            "steps": [
                {
                    "name": "Analysera innehåll",
                    "task": "Identifiera risker och beslutspunkter.",
                    "output_type": "json",
                }
            ],
        }
    )
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
            chosen_patterns=[],
            required_capabilities=["input_document", "output_mode_pass_through"],
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(
            state,
            ui_language="sv",
        ),
    )

    assert draft.steps[-1].name == "Skapa slutresultat"
    assert draft.steps[-1].instructions.startswith("Skapa slutresultatet")


def test_compile_outline_flow_quality_chain_preserves_all_semantic_steps() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Structured report",
            "plan_rationale": "Analyze uploaded material and produce a final PDF.",
            "steps": [
                {
                    "name": "Analyze material",
                    "task": "Analyze the uploaded material.",
                },
                {
                    "name": "Draft report",
                    "task": "Draft the report from the analysis.",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="pdf",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["multi_step_quality_chain"],
            required_capabilities=["input_document", "output_mode_pass_through"],
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Extract structured foundation",
        "Analyze material",
        "Draft report",
        "Review quality and gaps",
        "Create PDF",
    ]
    assert compiled.steps[-1].output_type.value == "pdf"
    assert validation.valid


def test_compile_outline_flow_quality_chain_wraps_rich_outline_from_pattern() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Detailed report",
            "plan_rationale": "The model already supplied a detailed semantic plan.",
            "steps": [
                {
                    "name": f"Phase {index}",
                    "task": f"Perform analysis phase {index}.",
                }
                for index in range(1, 5)
            ],
        }
    )
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="pdf",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=["multi_step_quality_chain"],
            required_capabilities=["input_document", "output_mode_pass_through"],
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.name for step in draft.steps] == [
        "Extract structured foundation",
        "Phase 1",
        "Phase 2",
        "Phase 3",
        "Phase 4",
        "Review quality and gaps",
        "Create PDF",
    ]
    assert draft.steps[-1].output_type.value == "pdf"
    assert compiled.steps[-1].output_type.value == "pdf"
    assert validation.valid


def test_compile_outline_flow_treats_output_fields_as_structured_signal() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Structured extraction",
            "plan_rationale": "Extract fields, then summarize.",
            "runtime_input": {"input_type": "text", "required": True},
            "final_output_type": "text",
            "steps": [
                {
                    "name": "Extract fields",
                    "task": "Extract stable facts.",
                    "output_type": "text",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "Concise summary.",
                            "required": True,
                        }
                    ],
                },
                {"name": "Write summary", "task": "Write the final summary."},
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)
    compiled = compile_create_draft(draft)

    assert draft.steps[0].output_type.value == "json"
    assert draft.steps[0].output_fields is not None
    assert compiled.steps[1].input_type.value == "json"
    assert compiled.steps[1].input_contract == compiled.steps[0].output_contract


def test_compile_outline_flow_preserves_requested_json_intermediate() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Structured intermediate",
            "plan_rationale": "Create an intermediate JSON result before prose.",
            "runtime_input": {"input_type": "text", "required": True},
            "final_output_type": "text",
            "steps": [
                {
                    "name": "Build structure",
                    "task": "Create structured intermediate data.",
                    "output_type": "json",
                },
                {"name": "Write answer", "task": "Write the final answer."},
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert draft.steps[0].output_type.value == "json"
    assert draft.steps[1].input_type.value == "json"
    assert compiled.steps[1].input_bindings is None
    assert validation.valid


def test_compile_create_draft_bridges_structured_previous_output_into_text_input() -> (
    None
):
    draft = FlowCreateDraft(
        flow_name="Structured bridge",
        plan_rationale="Extract JSON, then write text from the extracted structure.",
        steps=[
            CreateStepDraft(
                name="Extract fields",
                instructions="Extract stable fields.",
                input_source="flow_input",
                input_type="text",
                output_type="json",
                output_fields=[_field("summary", "string")],
            ),
            CreateStepDraft(
                name="Write body",
                instructions="Write the document body from the structured fields.",
                input_source="previous_step",
                input_type="text",
                output_type="text",
            ),
        ],
    )

    compiled = compile_create_draft(draft)

    assert compiled.steps[1].input_bindings == {
        "question": "{{ step_a.output.structured }}"
    }


def test_compile_create_draft_prefers_specific_previous_fields_for_text_input() -> None:
    draft = FlowCreateDraft(
        flow_name="Structured bridge",
        plan_rationale="Extract JSON, then write text from a selected field.",
        steps=[
            CreateStepDraft(
                name="Extract fields",
                instructions="Extract stable fields.",
                input_source="flow_input",
                input_type="text",
                output_type="json",
                output_fields=[
                    _field("summary", "string"),
                    _field("details", "string"),
                ],
            ),
            CreateStepDraft(
                name="Write body",
                instructions="Write the document body from selected fields.",
                input_source="previous_step",
                input_type="text",
                output_type="text",
                uses_previous_fields=[
                    {
                        "from_step": 1,
                        "field_path": "summary",
                        "label": "Summary",
                    }
                ],
            ),
        ],
    )

    compiled = compile_create_draft(draft)

    assert compiled.steps[1].input_bindings == {
        "question": "Summary: {{ step_a.output.structured.summary }}"
    }


def test_compile_outline_flow_logs_semantic_output_type_drift(
    caplog: pytest.LogCaptureFixture,
) -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "DOCX report",
            "plan_rationale": "Backend owns the artifact output.",
            "runtime_input": {"input_type": "document", "required": True},
            "final_output_type": "docx",
            "steps": [
                {
                    "name": "Write report",
                    "task": "Write report content.",
                    "output_type": "pdf",
                }
            ],
        }
    )

    with caplog.at_level(
        logging.INFO,
        logger="intric.flows.ai_builder.ai_builder_create_outline",
    ):
        draft = compile_outline_to_create_draft(outline)
    drift_records = [
        record
        for record in caplog.records
        if record.message == "ai_builder_skeleton_semantic_output_type_drift"
    ]

    assert [step.output_type.value for step in draft.steps] == ["text", "docx"]
    assert len(drift_records) == 1
    assert getattr(drift_records[0], "slot_id") == "final_response"
    assert getattr(drift_records[0], "slot_ordinal") == 0
    assert getattr(drift_records[0], "requested_output_type") == "pdf"
    assert getattr(drift_records[0], "enforced_output_type") == "text"


def test_compile_outline_flow_default_outline_stays_linear() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Synthesis",
            "plan_rationale": "Analyze two branches and synthesize.",
            "runtime_input": {"input_type": "text", "required": True},
            "final_output_type": "text",
            "steps": [
                {"name": "Branch A", "task": "Analyze from angle A."},
                {"name": "Branch B", "task": "Analyze from angle B."},
                {
                    "name": "Synthesize",
                    "task": "Synthesize all earlier work.",
                },
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.input_source.value for step in draft.steps] == [
        "flow_input",
        "previous_step",
        "previous_step",
    ]
    assert [step.input_source.value for step in compiled.steps] == [
        "flow_input",
        "previous_step",
        "previous_step",
    ]
    assert validation.valid
    assert not any(
        warning.code == "all_previous_overuse" for warning in validation.warnings
    )


def test_compile_outline_flow_preserves_step_mcp_refs() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "MCP-flöde",
            "plan_rationale": "Hämtar extern ärendedata innan analys.",
            "steps": [
                {
                    "name": "Hämta ärendedata",
                    "task": "Hämta aktuell status från ärendesystemet.",
                    "mcp_tool_refs": ["case_lookup_tool"],
                },
                {
                    "name": "Sammanfatta",
                    "task": "Sammanfatta statusen för användaren.",
                },
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)

    assert draft.steps[0].mcp_tool_refs == ["case_lookup_tool"]
    assert draft.steps[0].mcp_server_refs == []


def test_compile_outline_flow_does_not_fold_mcp_entry_step() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "MCP-flöde",
            "plan_rationale": "Hämtar externt underlag och skriver svar.",
            "runtime_input": {"input_type": "text", "required": True},
            "steps": [
                {
                    "name": "Hämta underlag",
                    "task": "Använd MCP-verktyget för att hämta underlag.",
                    "mcp_tool_refs": ["lookup_tool"],
                },
                {
                    "name": "Skriv svar",
                    "task": "Skriv ett tydligt svar.",
                },
            ],
        }
    )

    draft = compile_outline_to_create_draft(outline)

    assert [step.name for step in draft.steps] == ["Hämta underlag", "Skriv svar"]
    assert draft.steps[0].mcp_tool_refs == ["lookup_tool"]


def test_compile_outline_flow_comparison_pattern_owns_final_fan_in() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Comparison",
            "plan_rationale": "Analyze branches, then compare.",
            "steps": [
                {"name": "Extract source facts", "task": "Extract facts."},
                {"name": "Assess differences", "task": "Assess differences."},
                {"name": "Compare and conclude", "task": "Compare all work."},
            ],
        }
    )
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
            chosen_patterns=["comparison"],
            required_capabilities=["input_document", "output_mode_pass_through"],
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.input_source.value for step in draft.steps] == [
        "flow_input",
        "previous_step",
        "all_previous_steps",
    ]
    assert compiled.steps[2].input_bindings is None
    assert validation.valid
    assert not any(
        warning.code == "all_previous_overuse" for warning in validation.warnings
    )


def test_compile_outline_flow_multiple_document_scope_owns_one_fan_in() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Multi-document report",
            "plan_rationale": "Extract facts, analyze them, and write a report.",
            "final_output_type": "docx",
            "steps": [
                {
                    "name": "Extract source facts",
                    "task": "Extract structured facts from the uploaded material.",
                    "output_type": "json",
                    "output_fields": [{"name": "facts", "field_type": "array"}],
                },
                {
                    "name": "Analyze differences",
                    "task": "Analyze the extracted facts and highlight differences.",
                    "output_type": "json",
                    "output_fields": [{"name": "differences", "field_type": "array"}],
                },
                {
                    "name": "Write report",
                    "task": "Write the final report.",
                    "output_type": "docx",
                },
            ],
        }
    )
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="documents",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="docx_document",
            source="structured_answer",
            confidence="high",
        ),
        "document_material_scope": ResolvedSlot(
            name="document_material_scope",
            value="multiple_documents_case",
            source="heuristic",
            confidence="high",
        ),
    }

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert [step.input_source.value for step in draft.steps] == [
        "flow_input",
        "previous_step",
        "all_previous_steps",
    ]
    assert draft.steps[2].input_type.value == "text"
    assert compiled.steps[2].input_bindings is None
    assert validation.valid
    assert not any(
        warning.code == "all_previous_overuse" for warning in validation.warnings
    )


def test_compile_outline_flow_all_previous_with_form_fields_avoids_relisting_sources() -> (
    None
):
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Comparison with metadata",
            "plan_rationale": "Compare all prior work with runtime metadata.",
            "input_fields": [
                {
                    "variable_name": "audience",
                    "label": "Audience",
                    "field_type": "text",
                    "required": False,
                }
            ],
            "steps": [
                {"name": "Extract source facts", "task": "Extract facts."},
                {"name": "Assess differences", "task": "Assess differences."},
                {
                    "name": "Compare",
                    "task": "Compare all work.",
                    "uses_input_fields": ["audience"],
                },
            ],
        }
    )
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
            chosen_patterns=["comparison"],
            required_capabilities=["input_document", "output_mode_pass_through"],
        )
    )

    draft = compile_outline_to_create_draft(
        outline,
        context=outline_compile_context_from_planning_state(state),
    )
    compiled = compile_create_draft(draft)
    validation = validate_spec(compiled)

    assert draft.steps[2].input_source.value == "all_previous_steps"
    assert compiled.steps[2].input_bindings is None
    assert "audience: {{ audience }}" in compiled.steps[2].assistant_spec.instructions
    assert validation.valid
    assert not any(
        warning.code == "all_previous_overuse" for warning in validation.warnings
    )
