from __future__ import annotations

import pytest

from intric.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from intric.flows.ai_builder.ai_builder_create_compiler import compile_create_draft
from intric.flows.ai_builder.ai_builder_create_models import (
    CreateFormFieldDraft,
    CreateStepDraft,
    FlowCreateDraft,
    StructuredFieldDraft,
)
from intric.flows.ai_builder.ai_builder_create_outline import (
    MAX_OUTLINE_STEPS,
    OutlineFlowArgumentError,
    build_outline_flow_tool_schema,
    compile_outline_to_create_draft,
    outline_compile_context_from_planning_state,
    parse_outline_flow_arguments,
)
from intric.flows.ai_builder.ai_builder_create_validator import validate_create_draft
from intric.flows.ai_builder.ai_builder_flow_schema_values import (
    builder_output_type_values,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
    canonicalize_create_draft_resources,
)
from intric.flows.ai_builder.ai_builder_runtime_input_fields import (
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


def test_parse_outline_flow_ignores_backend_owned_legacy_step_mechanics() -> None:
    outline = parse_outline_flow_arguments(
        {
            "flow_name": "Legacy-shaped outline",
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


def test_parse_outline_flow_allows_advanced_step_counts_above_legacy_limit() -> None:
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


def test_parse_outline_flow_allows_advanced_step_counts_above_legacy_soft_cap() -> None:
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


def test_compile_outline_flow_adds_server_derived_runtime_field_hints() -> None:
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

    assert [field.variable_name for field in draft.form_fields] == [
        "audience",
        "detail_level",
    ]
    assert draft.steps[-1].uses_form_fields == ["audience", "detail_level"]
    assert compiled.steps[-1].input_bindings == {
        "question": "{{ indata_text }}\n\naudience: {{ audience }}\n"
        "detail_level: {{ detail_level }}"
    }
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

    assert [step.output_type.value for step in draft.steps] == ["text", "text", "pdf"]
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
    ]
    assert draft.steps[0].input_type.value == "audio"
    assert draft.steps[0].output_type.value == "text"
    assert draft.steps[0].runtime_upload is True
    assert draft.steps[1].input_source.value == "previous_step"
    assert draft.steps[1].input_type.value == "text"
    assert draft.steps[1].output_type.value == "pdf"
    assert compiled.steps[0].output_mode.value == "transcribe_only"
    assert compiled.steps[1].output_type.value == "pdf"
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
        "Create final output",
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
        "Create final output",
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
        "Create final output",
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
