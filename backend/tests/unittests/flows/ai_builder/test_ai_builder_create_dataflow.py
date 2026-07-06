import pytest

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    compile_create_steps_to_spec,
)
from eneo.flows.ai_builder.ai_builder_create_dataflow import (
    normalize_create_step_mechanics,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    RequestedOutputSections,
)
from eneo.flows.ai_builder.ai_builder_validator import validate_spec
from eneo.flows.ai_builder.planning_state import AggregationIntent
from eneo.flows.flow_authoring_spec import FormFieldSpec
from eneo.flows.input_binding_contract_rules import effective_question_binding


def test_create_dataflow_does_not_import_critic_invariants() -> None:
    from pathlib import Path

    import eneo.flows.ai_builder.ai_builder_create_dataflow as create_dataflow

    source = Path(create_dataflow.__file__).read_text(encoding="utf-8")

    assert "ai_builder_critic_invariants" not in source


def _field(
    name: str,
    field_type: str = "string",
    *,
    item_fields: list[StructuredFieldDraft] | None = None,
) -> StructuredFieldDraft:
    return StructuredFieldDraft(
        name=name,
        field_type=field_type,
        description=f"{name} field.",
        item_fields=item_fields,
    )


def _new_steps(steps: list[NewStepDraft | dict[str, object]]) -> list[NewStepDraft]:
    return [
        step if isinstance(step, NewStepDraft) else NewStepDraft.model_validate(step)
        for step in steps
    ]


def _assert_compiles_to_valid_spec(
    steps: list[NewStepDraft],
    *,
    flow_name: str = "Test flow",
    flow_description: str | None = None,
    form_fields: list[FormFieldSpec] | None = None,
    aggregation_intent: AggregationIntent = "linear",
) -> None:
    spec = compile_create_steps_to_spec(
        flow_name=flow_name,
        flow_description=flow_description,
        form_fields=form_fields,
        steps=steps,
        aggregation_intent=aggregation_intent,
    )
    assert validate_spec(spec).valid


def _normalize_steps(
    *,
    flow_name: str,
    steps: list[NewStepDraft | dict[str, object]],
    flow_description: str | None = None,
    form_fields: list[FormFieldSpec] | None = None,
    aggregation_intent: AggregationIntent = "linear",
) -> list[NewStepDraft]:
    return normalize_create_step_mechanics(
        steps=_new_steps(steps),
        form_fields=form_fields or [],
        flow_name=flow_name,
        flow_description=flow_description,
        aggregation_intent=aggregation_intent,
    )


def test_normalize_create_step_mechanics_rejects_unknown_previous_field_refs() -> None:
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        _normalize_steps(
            flow_name="Robust rapport",
            steps=[
                {
                    "name": "Extrahera data",
                    "instructions": "Extrahera strukturerade data.",
                    "input_source": "flow_input",
                    "input_type": "document",
                    "output_type": "json",
                    "runtime_required": True,
                    "output_fields": [_field("known_field")],
                },
                {
                    "name": "Skriv rapport",
                    "instructions": "Skriv rapport.",
                    "input_source": "previous_step",
                    "input_type": "json",
                    "output_type": "text",
                    "uses_previous_fields": [
                        {"from_step": 1, "field_path": "invented_field"},
                    ],
                },
            ],
        )

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.log_context["reason"] == "unknown_previous_field_path"


def test_normalize_create_step_mechanics_rejects_future_previous_field_refs() -> None:
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        _normalize_steps(
            flow_name="Robust rapport",
            steps=[
                {
                    "name": "Extrahera data",
                    "instructions": "Extrahera strukturerade data.",
                    "input_source": "flow_input",
                    "input_type": "document",
                    "output_type": "json",
                    "runtime_required": True,
                    "output_fields": [_field("known_field")],
                },
                {
                    "name": "Skriv rapport",
                    "instructions": "Skriv rapport.",
                    "input_source": "previous_step",
                    "input_type": "json",
                    "output_type": "text",
                    "uses_previous_fields": [
                        {"from_step": 2, "field_path": "future_field"},
                    ],
                },
            ],
        )

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.log_context["reason"] == "previous_field_step_not_prior"


def test_normalize_create_step_mechanics_rejects_missing_previous_field_schema() -> (
    None
):
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        _normalize_steps(
            flow_name="Robust rapport",
            steps=[
                {
                    "name": "Extrahera data",
                    "instructions": "Extrahera strukturerade data.",
                    "input_source": "flow_input",
                    "input_type": "document",
                    "output_type": "json",
                    "runtime_required": True,
                },
                {
                    "name": "Skriv rapport",
                    "instructions": "Skriv rapport.",
                    "input_source": "previous_step",
                    "input_type": "json",
                    "output_type": "text",
                    "uses_previous_fields": [
                        {"from_step": 1, "field_path": "known_field"},
                    ],
                },
            ],
        )

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert (
        exc_info.value.log_context["reason"]
        == "previous_field_source_missing_output_fields"
    )


def test_normalize_create_step_mechanics_rejects_invalid_previous_output_refs() -> None:
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        _normalize_steps(
            flow_name="Robust rapport",
            steps=[
                {
                    "name": "Transkribera",
                    "instructions": "Transkribera.",
                    "input_source": "flow_input",
                    "input_type": "audio",
                    "output_type": "text",
                    "runtime_required": True,
                },
                {
                    "name": "Extrahera metadata",
                    "instructions": "Extrahera metadata.",
                    "input_source": "previous_step",
                    "input_type": "text",
                    "output_type": "json",
                    "output_fields": [_field("titel")],
                },
                {
                    "name": "Skriv rapport",
                    "instructions": "Skriv rapport.",
                    "input_source": "previous_step",
                    "input_type": "text",
                    "output_type": "text",
                    "uses_previous_outputs": [
                        {"from_step": 2, "label": "Strukturerad metadata"},
                    ],
                },
            ],
        )

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.log_context["reason"] == "previous_output_source_not_text"


def test_normalize_create_step_mechanics_rejects_future_previous_output_refs() -> None:
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        _normalize_steps(
            flow_name="Robust rapport",
            steps=[
                {
                    "name": "Transkribera",
                    "instructions": "Transkribera.",
                    "input_source": "flow_input",
                    "input_type": "audio",
                    "output_type": "text",
                    "runtime_required": True,
                },
                {
                    "name": "Skriv rapport",
                    "instructions": "Skriv rapport.",
                    "input_source": "previous_step",
                    "input_type": "text",
                    "output_type": "text",
                    "uses_previous_outputs": [
                        {"from_step": 2, "label": "Eget steg"},
                    ],
                },
            ],
        )

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.log_context["reason"] == "previous_output_step_not_prior"


def test_normalize_create_step_mechanics_dedupes_duplicate_previous_refs() -> None:
    normalized = _normalize_steps(
        flow_name="Robust rapport",
        steps=[
            {
                "name": "Transkribera",
                "instructions": "Transkribera.",
                "input_source": "flow_input",
                "input_type": "audio",
                "output_type": "text",
                "runtime_required": True,
            },
            {
                "name": "Extrahera metadata",
                "instructions": "Extrahera metadata.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_fields": [_field("titel")],
            },
            {
                "name": "Skriv rapport",
                "instructions": "Skriv rapport.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
                "uses_previous_fields": [
                    {"from_step": 2, "field_path": "titel"},
                    {"from_step": 2, "field_path": "titel", "label": "Dublett"},
                ],
                "uses_previous_outputs": [
                    {"from_step": 1, "label": "Transkription"},
                    {"from_step": 1, "label": "Dublett"},
                ],
            },
        ],
    )

    _assert_compiles_to_valid_spec(normalized)
    assert [
        (ref.from_step, ref.field_path) for ref in normalized[2].uses_previous_fields
    ] == [(2, "titel")]
    assert [
        (ref.from_step, ref.label) for ref in normalized[2].uses_previous_outputs
    ] == [(1, "Transkription")]


def test_normalize_create_step_mechanics_restores_audio_source_material_underlag() -> (
    None
):
    normalized = _normalize_steps(
        flow_name="Mötesprotokoll från ljud till Word",
        steps=[
            {
                "name": "Transkribera ljud",
                "instructions": "Transkribera uppladdat ljud.",
                "input_source": "flow_input",
                "input_type": "audio",
                "output_type": "text",
                "runtime_required": True,
            },
            {
                "name": "Strukturera transkription",
                "instructions": "Strukturera transkriptionen.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_fields": [_field("transcription_text")],
            },
            {
                "name": "Identifiera mötesmetadata",
                "instructions": "Identifiera titel och organisation.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "json",
                "output_fields": [_field("meeting_title")],
            },
            {
                "name": "Skapa mötesprotokoll med fasta rubriker",
                "instructions": "Skapa protokollsektioner.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "json",
                "output_fields": [_field("protocol_sections")],
            },
            {
                "name": "Förbered DOCX-innehåll",
                "instructions": "Förbered dokumentets text.",
                "input_source": "all_previous_steps",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Skapa DOCX",
                "instructions": "Skapa slutdokumentet.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "docx",
                "document_delivery_mode": "generated",
            },
        ],
    )

    _assert_compiles_to_valid_spec(normalized)
    assert normalized[2].input_type == "text"
    assert [
        (ref.from_step, ref.label) for ref in normalized[2].uses_previous_outputs
    ] == [(1, "Källmaterial")]
    assert normalized[3].input_type == "text"
    assert [
        (ref.from_step, ref.label) for ref in normalized[3].uses_previous_outputs
    ] == [(1, "Källmaterial")]
    assert [
        (ref.from_step, ref.label) for ref in normalized[4].uses_previous_outputs
    ] == [(1, "Källmaterial")]
    assert {
        (ref.from_step, ref.field_path) for ref in normalized[4].uses_previous_fields
    } >= {
        (2, "transcription_text"),
        (3, "meeting_title"),
        (4, "protocol_sections"),
    }
    assert normalized[5].uses_previous_outputs == []


def test_normalize_create_step_mechanics_round_trips_backend_bound_underlag_refs() -> (
    None
):
    flow_name = "Mötesprotokoll från ljud till Word"
    once = _normalize_steps(
        flow_name=flow_name,
        steps=[
            {
                "name": "Transkribera ljud",
                "instructions": "Transkribera uppladdat ljud.",
                "input_source": "flow_input",
                "input_type": "audio",
                "output_type": "text",
                "runtime_required": True,
            },
            {
                "name": "Strukturera transkription",
                "instructions": "Strukturera transkriptionen.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_fields": [_field("transcription_text")],
            },
            {
                "name": "Identifiera mötesmetadata",
                "instructions": "Identifiera titel och organisation.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "json",
                "output_fields": [_field("meeting_title")],
            },
            {
                "name": "Skapa mötesprotokoll med fasta rubriker",
                "instructions": "Skapa protokollsektioner.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "json",
                "output_fields": [_field("protocol_sections")],
            },
            {
                "name": "Förbered DOCX-innehåll",
                "instructions": "Förbered dokumentets text.",
                "input_source": "all_previous_steps",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Skapa DOCX",
                "instructions": "Skapa slutdokumentet.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "docx",
                "document_delivery_mode": "generated",
            },
        ],
    )
    composer = once[4]

    assert {
        (ref.from_step, ref.field_path) for ref in composer.uses_previous_fields
    } >= {
        (2, "transcription_text"),
        (3, "meeting_title"),
        (4, "protocol_sections"),
    }
    assert [(ref.from_step, ref.label) for ref in composer.uses_previous_outputs] == [
        (1, "Källmaterial")
    ]

    _assert_compiles_to_valid_spec(once, flow_name=flow_name)
    assert _normalize_steps(flow_name=flow_name, steps=once) == once


def test_normalize_create_step_mechanics_detects_source_after_input_source_normalization() -> (
    None
):
    normalized = _normalize_steps(
        flow_name="Audio source report",
        steps=[
            {
                "name": "Transcribe audio",
                "instructions": "Transcribe the uploaded audio.",
                "input_type": "audio",
                "output_type": "text",
                "runtime_required": True,
            },
            {
                "name": "Extract facts",
                "instructions": "Extract the relevant facts.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_fields": [_field("finding")],
            },
            {
                "name": "Write answer",
                "instructions": "Write a concise answer from the facts.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "text",
            },
        ],
    )

    assert normalized[0].input_source == "flow_input"
    assert normalized[2].input_type == "text"
    assert [
        (ref.from_step, ref.label) for ref in normalized[2].uses_previous_outputs
    ] == [(1, "Source material")]
    assert [
        (ref.from_step, ref.field_path) for ref in normalized[2].uses_previous_fields
    ] == [(2, "finding")]


def test_omitted_previous_refs_use_declared_structured_fields_not_semantic_guess() -> (
    None
):
    normalized = _normalize_steps(
        flow_name="No implicit semantic match",
        steps=[
            {
                "name": "Läs underlag",
                "instructions": "Läs dokumentet.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "text",
                "runtime_required": True,
            },
            {
                "name": "Extrahera fält",
                "instructions": "Extrahera återanvändbara fält.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_fields": [
                    _field("sammanfattning_av_underlag"),
                    _field("tidplan"),
                ],
            },
            {
                "name": "Skriv tidsplanen",
                "instructions": "Skriv avsnittet om tidsplanen.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Skriv annat avsnitt",
                "instructions": "Skriv en annan kort del.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
            },
        ],
    )

    assert [
        (ref.from_step, ref.field_path) for ref in normalized[2].uses_previous_fields
    ] == [(2, "sammanfattning_av_underlag"), (2, "tidplan")]


def test_normalize_create_step_mechanics_keeps_non_adjacent_json_source() -> None:
    normalized = _normalize_steps(
        flow_name="Dokumentrapport",
        steps=[
            {
                "name": "Läs underlag",
                "instructions": "Läs dokumentet.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "text",
                "runtime_required": True,
            },
            {
                "name": "Extrahera metadata",
                "instructions": "Extrahera återanvändbara metadata.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_fields": [_field("titel"), _field("datum")],
            },
            {
                "name": "Extrahera slutsatser",
                "instructions": "Extrahera slutsatser.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "json",
                "output_fields": [_field("slutsatser")],
            },
            {
                "name": "Skriv rapport",
                "instructions": "Skriv rapporttexten.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
            },
        ],
    )

    writer = normalized[3]
    assert {(ref.from_step, ref.field_path) for ref in writer.uses_previous_fields} == {
        (2, "titel"),
        (2, "datum"),
        (3, "slutsatser"),
    }

    spec = compile_create_steps_to_spec(flow_name="Dokumentrapport", steps=normalized)
    question = effective_question_binding(spec.steps[3].input_bindings) or ""

    assert "{{ step_b.output.structured }}" in question
    assert "slutsatser field.: {{ step_c.output.structured.slutsatser }}" in question


def test_normalize_create_step_mechanics_folds_adjacent_source_json_refinement() -> (
    None
):
    normalized = _normalize_steps(
        flow_name="Dokumentanalys till PDF",
        steps=[
            {
                "name": "Läs dokument",
                "instructions": "Identifiera dokumentets titel.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "json",
                "output_fields": [_field("titel")],
                "runtime_required": True,
            },
            {
                "name": "Analysera dokumentets innehåll",
                "instructions": "Extrahera kategori och slutsats.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "json",
                "uses_previous_fields": [
                    {"from_step": 1, "field_path": "titel"},
                ],
                "output_fields": [_field("kategori"), _field("slutsats")],
            },
            {
                "name": "Skriv rapport",
                "instructions": "Skriv rapporten.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "text",
                "uses_previous_fields": [
                    {"from_step": 2, "field_path": "kategori"},
                ],
            },
            {
                "name": "Skapa PDF",
                "instructions": "Skapa PDF från rapporten.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "pdf",
                "document_delivery_mode": "generated",
            },
        ],
    )

    assert [step.name for step in normalized] == [
        "Läs dokument",
        "Skriv rapport",
        "Skapa PDF",
    ]
    assert [field.name for field in normalized[0].output_fields or []] == [
        "titel",
        "kategori",
        "slutsats",
    ]
    assert [
        (ref.from_step, ref.field_path) for ref in normalized[1].uses_previous_fields
    ] == [
        (1, "kategori"),
    ]

    spec = compile_create_steps_to_spec(
        flow_name="Dokumentanalys till PDF",
        steps=normalized,
    )
    assert len(spec.steps) == 3
    question = effective_question_binding(spec.steps[1].input_bindings) or ""
    assert "{{ step_a.output.structured.kategori }}" in question
    assert validate_spec(spec).valid


def test_normalize_create_step_mechanics_folds_redundant_text_render_helper() -> None:
    normalized = _normalize_steps(
        flow_name="Dokumentanalys till PDF",
        steps=[
            {
                "name": "Läs och strukturera dokumenten",
                "instructions": "Extrahera dokumentuppgifter.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "json",
                "output_fields": [_field("documents", "array")],
                "runtime_required": True,
            },
            {
                "name": "Sammanställ slutrapport",
                "instructions": "Skriv den färdiga rapporttexten.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "text",
                "uses_previous_fields": [
                    {"from_step": 1, "field_path": "documents"},
                ],
            },
            {
                "name": "Rendera PDF",
                "instructions": (
                    "Rendera den färdiga rapporttexten som ett komplett "
                    "PDF-dokument utan att lägga till ny information."
                ),
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
                "uses_previous_fields": [
                    {"from_step": 1, "field_path": "documents"},
                ],
                "uses_previous_outputs": [{"from_step": 2}],
            },
            {
                "name": "Skapa PDF",
                "instructions": "Skapa slutresultatet från föregående arbete.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "pdf",
                "document_delivery_mode": "generated",
            },
        ],
    )

    assert [step.name for step in normalized] == [
        "Läs och strukturera dokumenten",
        "Sammanställ slutrapport",
        "Skapa PDF",
    ]
    assert "utan att lägga till ny information" in (normalized[-1].instructions or "")


def test_normalize_create_step_mechanics_folds_all_previous_text_render_helper() -> (
    None
):
    normalized = _normalize_steps(
        flow_name="Dokumentanalys till PDF",
        steps=[
            {
                "name": "Läs och strukturera dokumenten",
                "instructions": "Extrahera dokumentuppgifter.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "json",
                "output_fields": [_field("documents", "array")],
                "runtime_required": True,
            },
            {
                "name": "Sammanställ rapporten",
                "instructions": "Skriv den färdiga rapporttexten.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "text",
                "uses_previous_fields": [
                    {"from_step": 1, "field_path": "documents"},
                ],
            },
            {
                "name": "Rendera PDF",
                "instructions": "Rendera rapporttexten som PDF.",
                "input_source": "all_previous_steps",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Skapa PDF",
                "instructions": "Skapa slutresultatet från föregående arbete.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "pdf",
                "document_delivery_mode": "generated",
            },
        ],
    )

    assert [step.name for step in normalized] == [
        "Läs och strukturera dokumenten",
        "Sammanställ rapporten",
        "Skapa PDF",
    ]
    assert normalized[-1].input_source == "previous_step"


def test_normalize_create_step_mechanics_keeps_substantive_artifact_body_step() -> None:
    normalized = _normalize_steps(
        flow_name="PDF report",
        steps=[
            {
                "name": "Extract",
                "instructions": "Extract facts.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "json",
                "output_fields": [_field("facts")],
            },
            {
                "name": "Skriv rapport",
                "instructions": "Skriv en kort analys.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "text",
                "uses_previous_fields": [{"from_step": 1, "field_path": "facts"}],
            },
            {
                "name": "Skapa PDF-rapport",
                "instructions": "Skapa en PDF-rapport med slutsats och risker.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Skapa PDF",
                "instructions": "Skapa slutdokumentet.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "pdf",
                "document_delivery_mode": "generated",
            },
        ],
    )

    assert [step.name for step in normalized] == [
        "Extract",
        "Skriv rapport",
        "Skapa PDF-rapport",
        "Skapa PDF",
    ]


def test_normalize_create_step_mechanics_keeps_json_refinement_with_external_context() -> (
    None
):
    normalized = _normalize_steps(
        flow_name="Dokumentanalys med regelverk",
        steps=[
            {
                "name": "Läs dokument",
                "instructions": "Identifiera dokumentets titel.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "json",
                "output_fields": [_field("titel")],
                "runtime_required": True,
            },
            {
                "name": "Jämför mot regelverk",
                "instructions": "Jämför dokumentet mot kunskapsunderlaget.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "json",
                "knowledge_refs": ["kb:lagstod"],
                "output_fields": [_field("regelavvikelse")],
            },
            {
                "name": "Skriv rapport",
                "instructions": "Skriv rapporten.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "text",
            },
        ],
    )

    assert [step.name for step in normalized] == [
        "Läs dokument",
        "Jämför mot regelverk",
        "Skriv rapport",
    ]
    assert [field.name for field in normalized[0].output_fields or []] == ["titel"]


def test_normalize_create_step_mechanics_preserves_model_declared_document_summary() -> (
    None
):
    normalized = _normalize_steps(
        flow_name="Dokumentanalys till PDF",
        steps=[
            {
                "name": "Läs dokument",
                "instructions": "Identifiera dokumentets titel.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "json",
                "output_fields": [
                    _field("documents", "array", item_fields=[_field("title")])
                ],
                "runtime_required": True,
            },
            {
                "name": "Analysera dokumentets innehåll",
                "instructions": "Extrahera kategori.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "json",
                "output_fields": [
                    _field(
                        "documents",
                        "array",
                        item_fields=[_field("category"), _field("summary")],
                    )
                ],
            },
            {
                "name": "Skriv rapport",
                "instructions": "Skriv en koncis sammanfattning per dokument.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "text",
            },
        ],
    )

    documents_field = (normalized[0].output_fields or [])[0]
    assert [field.name for field in documents_field.item_fields or []] == [
        "title",
        "category",
        "summary",
    ]


def test_targeted_underlag_cap_preserves_breadth_across_wide_priors() -> None:
    def fields(prefix: str) -> list[StructuredFieldDraft]:
        return [_field(f"{prefix}_{index}") for index in range(10)]

    normalized = _normalize_steps(
        flow_name="Bred sammanställning",
        steps=[
            {
                "name": "Extrahera första område",
                "instructions": "Extrahera första området.",
                "input_source": "flow_input",
                "input_type": "text",
                "output_type": "json",
                "output_fields": fields("first"),
            },
            {
                "name": "Extrahera andra område",
                "instructions": "Extrahera andra området.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "json",
                "output_fields": fields("second"),
            },
            {
                "name": "Skriv sammanställning",
                "instructions": "Skriv sammanställningen.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
            },
        ],
    )

    writer = normalized[2]
    assert [(ref.from_step, ref.field_path) for ref in writer.uses_previous_fields] == [
        (1, "first_0"),
        (2, "second_0"),
        (1, "first_1"),
        (2, "second_1"),
        (1, "first_2"),
        (2, "second_2"),
        (1, "first_3"),
        (2, "second_3"),
    ]


def test_normalize_create_step_mechanics_and_critic_share_targeted_underlag_policy() -> (
    None
):
    from eneo.flows.ai_builder.ai_builder_critic_invariants import (
        CRITIC_INVARIANTS,
        CriticContext,
        evaluate_critic_invariants,
    )
    from eneo.flows.ai_builder.ai_builder_framework_policy import (
        OutputIntentResolution,
    )
    from eneo.flows.ai_builder.ai_builder_planner_pattern_signals import (
        PlannerPatternSignals,
    )

    normalized = _normalize_steps(
        flow_name="PDF-rapport",
        steps=[
            {
                "name": "Läs PDF",
                "instructions": "Läs källdokumentet.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "text",
                "runtime_required": True,
            },
            {
                "name": "Extrahera bakgrund",
                "instructions": "Extrahera bakgrund.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_fields": [_field("background")],
            },
            {
                "name": "Extrahera resultat",
                "instructions": "Extrahera resultat.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "json",
                "output_fields": [_field("findings")],
            },
            {
                "name": "Förbered PDF-innehåll",
                "instructions": "Förbered rapportens text.",
                "input_source": "all_previous_steps",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Skapa PDF",
                "instructions": "Skapa slutdokumentet.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "pdf",
                "document_delivery_mode": "generated",
            },
        ],
    )

    composer = normalized[3]

    assert composer.input_source == "previous_step"
    assert {
        (ref.from_step, ref.field_path) for ref in composer.uses_previous_fields
    } >= {
        (2, "background"),
        (3, "findings"),
    }

    spec = compile_create_steps_to_spec(flow_name="PDF-rapport", steps=normalized)
    context = CriticContext(
        spec=spec,
        flow=None,
        answer_signals={},
        text="",
        requirements_text="",
        signal_text="",
        planner_patterns=PlannerPatternSignals(),
        output_intent=OutputIntentResolution(terminal_output="pdf_document"),
        mixed_audio_doc_input=False,
        requested_output_sections=RequestedOutputSections.empty(),
    )
    issue_ids = {
        issue.id
        for issue in evaluate_critic_invariants(
            context,
            invariants=CRITIC_INVARIANTS,
        )
    }

    assert "prefer_targeted_underlag_over_all_previous_steps" not in issue_ids


def test_normalize_create_step_mechanics_rewrites_final_assembler_to_section_outputs() -> (
    None
):
    section_steps = [
        {
            "name": f"Draft section {index}",
            "instructions": f"Write section {index}.",
            "input_source": "previous_step",
            "input_type": "text",
            "output_type": "text",
            "uses_previous_fields": [{"from_step": 2, "field_path": "facts"}],
        }
        for index in range(1, 9)
    ]
    normalized = _normalize_steps(
        flow_name="Document report",
        steps=[
            {
                "name": "Read source material",
                "instructions": "Read the uploaded material.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "text",
                "runtime_required": True,
            },
            {
                "name": "Extract reusable facts",
                "instructions": "Extract reusable facts.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_fields": [_field("facts")],
            },
            *section_steps,
            {
                "name": "Assemble document body",
                "instructions": "Assemble the final body from the drafted sections.",
                "input_source": "all_previous_steps",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Render document",
                "instructions": "Create the final document.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "docx",
                "document_delivery_mode": "generated",
            },
        ],
    )

    assembler = normalized[-2]

    assert assembler.input_source == "previous_step"
    assert [ref.from_step for ref in assembler.uses_previous_outputs] == list(
        range(3, 11)
    )
    assert assembler.uses_previous_fields == []

    spec = compile_create_steps_to_spec(flow_name="Document report", steps=normalized)
    question = effective_question_binding(spec.steps[-2].input_bindings) or ""

    assert "{{ step_a.output.text }}" not in question
    assert "{{ step_b.output.structured" not in question
    for step_ref in (
        "step_c",
        "step_d",
        "step_e",
        "step_f",
        "step_g",
        "step_h",
        "step_i",
        "step_j",
    ):
        assert f"{{{{ {step_ref}.output.text }}}}" in question


def test_final_assembler_references_section_text_and_structured_json_priors() -> None:
    from eneo.flows.ai_builder.ai_builder_critic_invariants import (
        CRITIC_INVARIANTS,
        CriticContext,
        evaluate_critic_invariants,
    )
    from eneo.flows.ai_builder.ai_builder_framework_policy import (
        OutputIntentResolution,
    )
    from eneo.flows.ai_builder.ai_builder_planner_pattern_signals import (
        PlannerPatternSignals,
    )

    normalized = _normalize_steps(
        flow_name="Document analysis report",
        steps=[
            {
                "name": "Read source material",
                "instructions": "Read the uploaded material.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "text",
                "runtime_required": True,
            },
            {
                "name": "Extract document identity",
                "instructions": "Extract title and year.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_fields": [_field("title"), _field("year")],
            },
            {
                "name": "Extract document meaning",
                "instructions": "Extract category and conclusion.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "json",
                "output_fields": [_field("category"), _field("conclusion")],
            },
            {
                "name": "Draft summary section",
                "instructions": "Draft the concise summary section.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "text",
                "uses_previous_fields": [
                    {"from_step": 2, "field_path": "title"},
                    {"from_step": 3, "field_path": "category"},
                ],
            },
            {
                "name": "Draft conclusion section",
                "instructions": "Draft the conclusion section.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "text",
                "uses_previous_fields": [
                    {"from_step": 2, "field_path": "year"},
                    {"from_step": 3, "field_path": "conclusion"},
                ],
            },
            {
                "name": "Assemble PDF body",
                "instructions": "Assemble the final report body.",
                "input_source": "all_previous_steps",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Render PDF",
                "instructions": "Create the PDF report.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "pdf",
                "document_delivery_mode": "generated",
            },
        ],
    )

    assembler = normalized[-2]

    assert assembler.input_source == "previous_step"
    assert [ref.from_step for ref in assembler.uses_previous_outputs] == [4, 5]
    assert {
        (ref.from_step, ref.field_path) for ref in assembler.uses_previous_fields
    } == {
        (2, "title"),
        (2, "year"),
        (3, "category"),
        (3, "conclusion"),
    }

    spec = compile_create_steps_to_spec(
        flow_name="Document analysis report",
        steps=normalized,
    )
    question = effective_question_binding(spec.steps[-2].input_bindings) or ""

    assert "{{ step_a.output.text }}" not in question
    assert "{{ step_d.output.text }}" in question
    assert "{{ step_e.output.text }}" in question
    assert "{{ step_b.output.structured }}" in question
    assert "{{ step_c.output.structured }}" in question

    issue_ids = {
        issue.id
        for issue in evaluate_critic_invariants(
            CriticContext(
                spec=spec,
                flow=None,
                answer_signals={},
                text="",
                requirements_text="",
                signal_text="",
                planner_patterns=PlannerPatternSignals(),
                output_intent=OutputIntentResolution(terminal_output="pdf_document"),
                mixed_audio_doc_input=False,
                requested_output_sections=RequestedOutputSections.empty(),
            ),
            invariants=CRITIC_INVARIANTS,
        )
    }

    assert "final_text_step_must_reference_relevant_structured_outputs" not in issue_ids


def test_previous_step_composer_completes_partial_structured_json_refs() -> None:
    from eneo.flows.ai_builder.ai_builder_critic_invariants import (
        CRITIC_INVARIANTS,
        CriticContext,
        evaluate_critic_invariants,
    )
    from eneo.flows.ai_builder.ai_builder_framework_policy import (
        OutputIntentResolution,
    )
    from eneo.flows.ai_builder.ai_builder_planner_pattern_signals import (
        PlannerPatternSignals,
    )

    normalized = _normalize_steps(
        flow_name="Document metadata report",
        steps=[
            {
                "name": "Read source material",
                "instructions": "Read the uploaded material.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "text",
                "runtime_required": True,
            },
            {
                "name": "Extract document identity",
                "instructions": "Extract title and year.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_fields": [_field("title"), _field("year")],
            },
            {
                "name": "Extract document classification",
                "instructions": "Extract category and conclusion.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "json",
                "output_fields": [_field("category"), _field("conclusion")],
            },
            {
                "name": "Write report body",
                "instructions": "Write the final report body.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "text",
                "uses_previous_fields": [{"from_step": 3, "field_path": "conclusion"}],
            },
            {
                "name": "Render PDF",
                "instructions": "Create the PDF report.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "pdf",
                "document_delivery_mode": "generated",
            },
        ],
    )

    composer = normalized[-2]

    assert {
        (ref.from_step, ref.field_path) for ref in composer.uses_previous_fields
    } == {
        (2, "title"),
        (2, "year"),
        (3, "category"),
        (3, "conclusion"),
    }
    assert [ref.from_step for ref in composer.uses_previous_outputs] == [1]

    spec = compile_create_steps_to_spec(
        flow_name="Document metadata report",
        steps=normalized,
    )
    question = effective_question_binding(spec.steps[-2].input_bindings) or ""

    assert "{{ step_b.output.structured }}" in question
    assert "{{ step_c.output.structured }}" in question

    issue_ids = {
        issue.id
        for issue in evaluate_critic_invariants(
            CriticContext(
                spec=spec,
                flow=None,
                answer_signals={},
                text="",
                requirements_text="",
                signal_text="",
                planner_patterns=PlannerPatternSignals(),
                output_intent=OutputIntentResolution(terminal_output="pdf_document"),
                mixed_audio_doc_input=False,
                requested_output_sections=RequestedOutputSections.empty(),
            ),
            invariants=CRITIC_INVARIANTS,
        )
    }

    assert "final_text_step_must_reference_relevant_structured_outputs" not in issue_ids


def test_previous_step_composer_keeps_non_adjacent_ref_when_previous_json_is_implicit() -> (
    None
):
    from eneo.flows.ai_builder.ai_builder_critic_invariants import (
        CRITIC_INVARIANTS,
        CriticContext,
        evaluate_critic_invariants,
    )
    from eneo.flows.ai_builder.ai_builder_framework_policy import (
        OutputIntentResolution,
    )
    from eneo.flows.ai_builder.ai_builder_planner_pattern_signals import (
        PlannerPatternSignals,
    )

    normalized = _normalize_steps(
        flow_name="Document metadata report",
        steps=[
            {
                "name": "Read source material",
                "instructions": "Read the uploaded material.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "text",
                "runtime_required": True,
            },
            {
                "name": "Extract document identity",
                "instructions": "Extract title and year.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_fields": [_field("title"), _field("year")],
            },
            {
                "name": "Extract document classification",
                "instructions": "Extract category and conclusion.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "json",
                "output_fields": [_field("category"), _field("conclusion")],
            },
            {
                "name": "Write report body",
                "instructions": "Write the final report body.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "text",
                "uses_previous_fields": [{"from_step": 2, "field_path": "title"}],
            },
            {
                "name": "Render PDF",
                "instructions": "Create the PDF report.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "pdf",
                "document_delivery_mode": "generated",
            },
        ],
    )

    composer = normalized[-2]

    assert [
        (ref.from_step, ref.field_path) for ref in composer.uses_previous_fields
    ] == [(2, "title")]
    assert composer.uses_previous_outputs == []

    spec = compile_create_steps_to_spec(
        flow_name="Document metadata report",
        steps=normalized,
    )
    question = effective_question_binding(spec.steps[-2].input_bindings) or ""

    assert "{{ step_b.output.structured.title }}" in question
    assert "{{ step_c.output.structured }}" in question

    issue_ids = {
        issue.id
        for issue in evaluate_critic_invariants(
            CriticContext(
                spec=spec,
                flow=None,
                answer_signals={},
                text="",
                requirements_text="",
                signal_text="",
                planner_patterns=PlannerPatternSignals(),
                output_intent=OutputIntentResolution(terminal_output="pdf_document"),
                mixed_audio_doc_input=False,
                requested_output_sections=RequestedOutputSections.empty(),
            ),
            invariants=CRITIC_INVARIANTS,
        )
    }

    assert "final_text_step_must_reference_relevant_structured_outputs" not in issue_ids


def test_normalize_create_step_mechanics_preserves_final_assembler_field_refs() -> None:
    normalized = _normalize_steps(
        flow_name="Document report with audit facts",
        steps=[
            {
                "name": "Extract facts",
                "instructions": "Extract reusable facts.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "json",
                "runtime_required": True,
                "output_fields": [_field("facts")],
            },
            {
                "name": "Draft section one",
                "instructions": "Write section one.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
                "uses_previous_fields": [{"from_step": 1, "field_path": "facts"}],
            },
            {
                "name": "Draft section two",
                "instructions": "Write section two.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
                "uses_previous_fields": [{"from_step": 1, "field_path": "facts"}],
            },
            {
                "name": "Assemble document body",
                "instructions": "Assemble the final body from the drafted sections.",
                "input_source": "all_previous_steps",
                "input_type": "text",
                "output_type": "text",
                "uses_previous_fields": [{"from_step": 1, "field_path": "facts"}],
            },
            {
                "name": "Render document",
                "instructions": "Create the final document.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "docx",
            },
        ],
    )

    assembler = normalized[-2]

    assert [
        (ref.from_step, ref.field_path) for ref in assembler.uses_previous_fields
    ] == [(1, "facts")]
    assert [ref.from_step for ref in assembler.uses_previous_outputs] == [2, 3]


def test_normalize_create_step_mechanics_rewrites_final_assembler_for_aggregate_intent() -> (
    None
):
    from eneo.flows.ai_builder.ai_builder_critic_invariants import (
        CRITIC_INVARIANTS,
        CriticContext,
        evaluate_critic_invariants,
    )
    from eneo.flows.ai_builder.ai_builder_framework_policy import (
        OutputIntentResolution,
    )
    from eneo.flows.ai_builder.ai_builder_planner_pattern_signals import (
        PlannerPatternSignals,
    )

    normalized = _normalize_steps(
        flow_name="Aggregate report",
        steps=[
            {
                "name": "Part A",
                "instructions": "Write part A.",
                "input_source": "flow_input",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Part B",
                "instructions": "Write part B.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Aggregate body",
                "instructions": "Aggregate all prior text.",
                "input_source": "all_previous_steps",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Render PDF",
                "instructions": "Create PDF.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "pdf",
            },
        ],
        aggregation_intent="aggregate",
    )

    assert normalized[-2].input_source == "previous_step"
    assert [ref.from_step for ref in normalized[-2].uses_previous_outputs] == [
        1,
        2,
    ]

    spec = compile_create_steps_to_spec(
        flow_name="Aggregate report",
        steps=normalized,
        aggregation_intent="aggregate",
    )
    context = CriticContext(
        spec=spec,
        flow=None,
        answer_signals={},
        text="",
        requirements_text="",
        signal_text="",
        planner_patterns=PlannerPatternSignals(),
        output_intent=OutputIntentResolution(terminal_output="pdf_document"),
        mixed_audio_doc_input=False,
        requested_output_sections=RequestedOutputSections.empty(),
        aggregation_intent="aggregate",
    )
    issue_ids = {
        issue.id
        for issue in evaluate_critic_invariants(
            context,
            invariants=CRITIC_INVARIANTS,
        )
    }

    assert "multi_document_compare_requires_all_previous_steps" not in issue_ids
    assert "final_assembler_must_reference_explicit_section_outputs" not in issue_ids
    assert "terminal_renderer_must_consume_previous_composer" not in issue_ids


def test_normalize_create_step_mechanics_keeps_final_assembler_broad_for_compare_intent() -> (
    None
):
    normalized = _normalize_steps(
        flow_name="Compare report",
        steps=[
            {
                "name": "Part A",
                "instructions": "Write part A.",
                "input_source": "flow_input",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Part B",
                "instructions": "Write part B.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Compare body",
                "instructions": "Compare all prior text.",
                "input_source": "all_previous_steps",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Render PDF",
                "instructions": "Create PDF.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "pdf",
            },
        ],
        aggregation_intent="compare",
    )

    assert normalized[-2].input_source == "all_previous_steps"
    assert normalized[-2].uses_previous_outputs == []


def test_normalize_create_step_mechanics_rewrites_terminal_renderer_all_previous() -> (
    None
):
    normalized = _normalize_steps(
        flow_name="Document report",
        steps=[
            {
                "name": "Read source",
                "instructions": "Read the uploaded material.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "text",
                "runtime_required": True,
            },
            {
                "name": "Extract facts",
                "instructions": "Extract facts.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_fields": [_field("facts")],
            },
            {
                "name": "Compose body",
                "instructions": "Compose the document body.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "text",
                "uses_previous_fields": [{"from_step": 2, "field_path": "facts"}],
            },
            {
                "name": "Render PDF",
                "instructions": "Render the body.",
                "input_source": "all_previous_steps",
                "input_type": "text",
                "output_type": "pdf",
            },
        ],
    )

    renderer = normalized[-1]

    assert renderer.input_source == "previous_step"
    assert renderer.uses_previous_fields == []
    assert renderer.uses_previous_outputs == []


def test_normalize_create_step_mechanics_rewrites_terminal_renderer_for_aggregate_intent() -> (
    None
):
    normalized = _normalize_steps(
        flow_name="Aggregate report",
        steps=[
            {
                "name": "Part one",
                "instructions": "Write part one.",
                "input_source": "flow_input",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Render PDF",
                "instructions": "Render all parts.",
                "input_source": "all_previous_steps",
                "input_type": "text",
                "output_type": "pdf",
            },
        ],
        aggregation_intent="aggregate",
    )

    assert normalized[-1].input_source == "previous_step"


def test_normalize_create_step_mechanics_keeps_terminal_renderer_without_text_composer() -> (
    None
):
    normalized = _normalize_steps(
        flow_name="Structured artifact",
        steps=[
            {
                "name": "Extract facts",
                "instructions": "Extract facts.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "json",
                "runtime_required": True,
                "output_fields": [_field("facts")],
            },
            {
                "name": "Normalize facts",
                "instructions": "Normalize facts.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "json",
                "output_fields": [_field("normalized_facts")],
            },
            {
                "name": "Render PDF",
                "instructions": "Render facts.",
                "input_source": "all_previous_steps",
                "input_type": "text",
                "output_type": "pdf",
            },
        ],
    )

    assert normalized[-1].input_source == "all_previous_steps"


def test_normalize_create_step_mechanics_rewrites_assembler_before_terminal_renderer() -> (
    None
):
    normalized = _normalize_steps(
        flow_name="Document report",
        steps=[
            {
                "name": "Extract facts",
                "instructions": "Extract facts.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "json",
                "runtime_required": True,
                "output_fields": [_field("facts")],
            },
            {
                "name": "Section one",
                "instructions": "Write section one.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
                "uses_previous_fields": [{"from_step": 1, "field_path": "facts"}],
            },
            {
                "name": "Section two",
                "instructions": "Write section two.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
                "uses_previous_fields": [{"from_step": 1, "field_path": "facts"}],
            },
            {
                "name": "Assemble body",
                "instructions": "Assemble the sections.",
                "input_source": "all_previous_steps",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Render PDF",
                "instructions": "Render the body.",
                "input_source": "all_previous_steps",
                "input_type": "text",
                "output_type": "pdf",
            },
        ],
    )

    assert normalized[-2].input_source == "previous_step"
    assert [ref.from_step for ref in normalized[-2].uses_previous_outputs] == [
        2,
        3,
    ]
    assert normalized[-1].input_source == "previous_step"
    assert normalized[-1].uses_previous_outputs == []


def test_normalize_create_step_mechanics_rewrites_assembler_before_review_and_renderer() -> (
    None
):
    normalized = _normalize_steps(
        flow_name="Document report with final review",
        steps=[
            {
                "name": "Extract facts",
                "instructions": "Extract facts.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "json",
                "runtime_required": True,
                "output_fields": [_field("facts")],
            },
            {
                "name": "Section one",
                "instructions": "Write section one.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
                "uses_previous_fields": [{"from_step": 1, "field_path": "facts"}],
            },
            {
                "name": "Section two",
                "instructions": "Write section two.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
                "uses_previous_fields": [{"from_step": 1, "field_path": "facts"}],
            },
            {
                "name": "Assemble body",
                "instructions": "Assemble the sections.",
                "input_source": "all_previous_steps",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Review body",
                "instructions": "Review the assembled body.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Render DOCX",
                "instructions": "Render the body.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "docx",
            },
        ],
    )

    assembler = normalized[3]
    assert assembler.input_source == "previous_step"
    assert [ref.from_step for ref in assembler.uses_previous_outputs] == [2, 3]
    assert normalized[4].input_source == "previous_step"
    assert normalized[5].input_source == "previous_step"


def test_normalize_create_step_mechanics_keeps_non_source_text_step_label() -> None:
    normalized = _normalize_steps(
        flow_name="Textbaserad sammanställning",
        steps=[
            {
                "name": "Samla anteckningar",
                "instructions": "Ta emot manuella anteckningar.",
                "input_source": "flow_input",
                "input_type": "text",
                "output_type": "text",
            },
            {
                "name": "Extrahera kontext",
                "instructions": "Extrahera kontext.",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_fields": [_field("context")],
            },
            {
                "name": "Extrahera beslut",
                "instructions": "Extrahera beslut.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "json",
                "output_fields": [_field("decisions")],
            },
            {
                "name": "Skriv rapport",
                "instructions": "Skriv rapport.",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "text",
            },
        ],
    )

    assert [
        (ref.from_step, ref.label) for ref in normalized[3].uses_previous_outputs
    ] == [(1, "Samla anteckningar")]


def test_normalize_create_step_mechanics_prunes_unknown_form_field_refs() -> None:
    form_fields = [
        FormFieldSpec(
            name="case_id",
            label="Case ID",
            type="text",
            required=True,
        )
    ]
    normalized = _normalize_steps(
        flow_name="Robust formulärflöde",
        form_fields=form_fields,
        steps=[
            {
                "name": "Analysera",
                "instructions": "Analysera texten.",
                "input_source": "flow_input",
                "input_type": "text",
                "output_type": "text",
                "uses_form_fields": ["case_id", "invented_case_owner"],
            }
        ],
    )

    _assert_compiles_to_valid_spec(
        normalized,
        flow_name="Robust formulärflöde",
        form_fields=form_fields,
    )
    assert normalized[0].uses_form_fields == ["case_id"]


def test_normalize_create_step_mechanics_fixes_safe_step_invariants() -> None:
    normalized = _normalize_steps(
        flow_name="Mekaniskt robust flöde",
        steps=[
            {
                "name": "Ta emot dokument",
                "instructions": "Läs dokumentet.",
                "input_source": "previous_step",
                "input_type": "document",
                "output_type": "text",
                "runtime_required": True,
                "citations_requested": True,
            },
            {
                "name": "Sammanställ",
                "instructions": "Sammanställ tidigare steg.",
                "input_source": "flow_input",
                "input_type": "json",
                "output_type": "text",
                "document_delivery_mode": "generated",
            },
            {
                "name": "Sluttext",
                "instructions": "Skriv sluttext.",
                "input_source": "all_previous_steps",
                "input_type": "json",
                "output_type": "json",
                "citations_requested": True,
                "output_fields": [_field("summary")],
            },
        ],
    )

    compiled = compile_create_steps_to_spec(
        flow_name="Mekaniskt robust flöde",
        steps=normalized,
    )
    runtime_input = compiled.steps[0].input_config["runtime_input"]

    assert normalized[0].input_source == "flow_input"
    assert runtime_input["enabled"] is True
    assert runtime_input["input_format"] == "document"
    assert runtime_input["required"] is True
    assert normalized[1].input_source == "previous_step"
    assert normalized[1].input_type == "json"
    assert normalized[1].document_delivery_mode == "not_applicable"
    assert normalized[2].input_type == "text"
    assert normalized[2].citations_requested is False
    _assert_compiles_to_valid_spec(normalized)
