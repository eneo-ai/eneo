from __future__ import annotations

import pytest

from intric.flows.ai_builder.ai_builder_create_compiler import compile_create_draft
from intric.flows.ai_builder.ai_builder_create_models import (
    CreateFormFieldDraft,
    CreateStepDraft,
    FlowCreateDraft,
    StructuredFieldDraft,
)
from intric.flows.ai_builder.ai_builder_create_validator import validate_create_draft
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
    canonicalize_create_draft_resources,
)
from intric.flows.ai_builder.ai_builder_validator import validate_spec


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


def test_compile_create_draft_generates_runtime_upload_contracts_and_form_fields() -> None:
    draft = FlowCreateDraft(
        flow_name="Kommunärendeanalys",
        flow_description="Analyserar dokumentpaket.",
        plan_rationale="Strukturerad extraktion först för säkrare vidare analys.",
        assumptions=["PDF-paketet hör till ett och samma ärende."],
        form_fields=[
            CreateFormFieldDraft(
                variable_name="ärendenummer",
                label="Ärendenummer",
                field_type="text",
                required=True,
            ),
            CreateFormFieldDraft(
                variable_name="ansvarig_nämnd",
                label="Ansvarig nämnd",
                field_type="select",
                required=True,
                options=["Kommunstyrelsen", "Socialnämnden"],
            ),
        ],
        steps=[
            CreateStepDraft(
                name="Extrahera juridiska risker",
                instructions="Extrahera juridiska risker och ekonomiska konsekvenser.",
                input_source="flow_input",
                input_type="document",
                output_type="json",
                runtime_upload=True,
                runtime_required=True,
                runtime_max_files=5,
                uses_form_fields=["ärendenummer", "ansvarig_nämnd"],
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
                        "ekonomiska_konsekvenser",
                        "array",
                        description="Ekonomiska effekter.",
                        item_fields=[
                            _field("sammanfattning", "string", description="Kort summering."),
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

    assert compiled.flow_name == "Kommunärendeanalys"
    assert [step.plan_step_ref for step in compiled.steps] == ["step_a", "step_b"]
    assert compiled.form_fields is not None
    assert compiled.form_fields[0].name == "ärendenummer"
    assert compiled.form_fields[1].options == ["Kommunstyrelsen", "Socialnämnden"]

    first_step = compiled.steps[0]
    assert first_step.input_config is not None
    runtime_input = first_step.input_config["runtime_input"]
    assert runtime_input["enabled"] is True
    assert runtime_input["required"] is True
    assert runtime_input["max_files"] == 5
    assert runtime_input["input_format"] == "document"
    assert first_step.input_bindings is None
    assert "{{ ärendenummer }}" in first_step.assistant_spec.instructions
    assert "{{ ansvarig_nämnd }}" in first_step.assistant_spec.instructions
    assert "Required JSON fields:" in first_step.assistant_spec.instructions
    assert "risker" in first_step.assistant_spec.instructions
    assert "ekonomiska_konsekvenser" in first_step.assistant_spec.instructions
    assert first_step.output_contract is not None
    assert first_step.output_contract["properties"]["risker"]["type"] == "array"
    assert (
        first_step.output_contract["properties"]["risker"]["items"]["properties"]["titel"]["type"]
        == "string"
    )

    second_step = compiled.steps[1]
    assert second_step.input_bindings is not None
    assert second_step.input_bindings["question"] == "{{ step_a.output.structured }}"
    assert second_step.output_config == {"citation_mode": "inline_inref_sidecar"}

    validation = validate_spec(compiled)
    assert validation.valid
    assert not any(warning.code == "contract_instruction_mismatch" for warning in validation.warnings)


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
    assert step.input_bindings is None
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
    assert any(error.code == "template_fill_requires_docx" for error in validation.errors)


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
