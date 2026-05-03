from intric.flows.ai_builder.ai_builder_create_dataflow import (
    normalize_create_draft_mechanics,
    strip_malformed_previous_field_refs,
)
from intric.flows.ai_builder.ai_builder_create_models import (
    CreateFormFieldDraft,
    FlowCreateDraft,
)
from intric.flows.ai_builder.ai_builder_create_validator import validate_create_draft
from intric.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft


def _field(name: str) -> StructuredFieldDraft:
    return StructuredFieldDraft(
        name=name,
        field_type="string",
        description=f"{name} field.",
    )


def test_normalize_create_draft_mechanics_prunes_unknown_previous_field_refs() -> None:
    draft = FlowCreateDraft(
        flow_name="Robust rapport",
        plan_rationale="Skapa rapport från strukturerade steg.",
        steps=[
            {
                "name": "Extrahera data",
                "instructions": "Extrahera strukturerade data.",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "json",
                "runtime_upload": True,
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
                    {"from_step": 1, "field_path": "known_field"},
                    {"from_step": 1, "field_path": "invented_field"},
                    {"from_step": 2, "field_path": "future_field"},
                ],
            },
        ],
    )

    assert not validate_create_draft(draft).valid

    normalized = normalize_create_draft_mechanics(draft)

    assert validate_create_draft(normalized).valid
    assert [ref.field_path for ref in normalized.steps[1].uses_previous_fields] == [
        "known_field"
    ]


def test_normalize_create_draft_mechanics_prunes_invalid_previous_output_refs() -> None:
    draft = FlowCreateDraft(
        flow_name="Robust rapport",
        plan_rationale="Återanvänd tidigare textutdata.",
        steps=[
            {
                "name": "Transkribera",
                "instructions": "Transkribera.",
                "input_source": "flow_input",
                "input_type": "audio",
                "output_type": "text",
                "runtime_upload": True,
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
                    {"from_step": 1, "label": "Transkription"},
                    {"from_step": 2, "label": "Strukturerad metadata"},
                    {"from_step": 3, "label": "Eget steg"},
                    {"from_step": 9, "label": "Okänt"},
                    {"from_step": 1, "label": "Dublett"},
                ],
            },
        ],
    )

    assert not validate_create_draft(draft).valid

    normalized = normalize_create_draft_mechanics(draft)

    assert validate_create_draft(normalized).valid
    assert [
        (ref.from_step, ref.label) for ref in normalized.steps[2].uses_previous_outputs
    ] == [(1, "Transkription")]


def test_normalize_create_draft_mechanics_restores_audio_source_material_underlag() -> (
    None
):
    draft = FlowCreateDraft(
        flow_name="Mötesprotokoll från ljud till Word",
        plan_rationale="Transkribera ljud och skapa DOCX-protokoll.",
        steps=[
            {
                "name": "Transkribera ljud",
                "instructions": "Transkribera uppladdat ljud.",
                "input_source": "flow_input",
                "input_type": "audio",
                "output_type": "text",
                "runtime_upload": True,
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

    normalized = normalize_create_draft_mechanics(draft)

    assert validate_create_draft(normalized).valid
    assert normalized.steps[2].input_type == "text"
    assert [
        (ref.from_step, ref.label) for ref in normalized.steps[2].uses_previous_outputs
    ] == [(1, "Källmaterial")]
    assert normalized.steps[3].input_type == "text"
    assert [
        (ref.from_step, ref.label) for ref in normalized.steps[3].uses_previous_outputs
    ] == [(1, "Källmaterial")]
    assert normalized.steps[4].uses_previous_outputs == []
    assert normalized.steps[5].uses_previous_outputs == []


def test_normalize_create_draft_mechanics_prunes_unknown_form_field_refs() -> None:
    draft = FlowCreateDraft(
        flow_name="Robust formulärflöde",
        plan_rationale="Använd runtime metadata om den finns.",
        form_fields=[
            CreateFormFieldDraft(
                variable_name="case_id",
                label="Case ID",
                field_type="text",
                required=True,
            )
        ],
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

    assert not validate_create_draft(draft).valid

    normalized = normalize_create_draft_mechanics(draft)

    assert validate_create_draft(normalized).valid
    assert normalized.steps[0].uses_form_fields == ["case_id"]


def test_normalize_create_draft_mechanics_fixes_safe_step_invariants() -> None:
    draft = FlowCreateDraft(
        flow_name="Mekaniskt robust flöde",
        plan_rationale="Normalisera endast backendägda mekaniker.",
        steps=[
            {
                "name": "Ta emot dokument",
                "instructions": "Läs dokumentet.",
                "input_source": "previous_step",
                "input_type": "document",
                "output_type": "text",
                "runtime_upload": False,
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

    assert not validate_create_draft(draft).valid

    normalized = normalize_create_draft_mechanics(draft)

    assert normalized.steps[0].input_source == "flow_input"
    assert normalized.steps[0].runtime_upload is True
    assert normalized.steps[0].runtime_required is True
    assert normalized.steps[1].input_source == "previous_step"
    assert normalized.steps[1].input_type == "json"
    assert normalized.steps[1].document_delivery_mode == "not_applicable"
    assert normalized.steps[2].input_type == "text"
    assert normalized.steps[2].citations_requested is False
    assert validate_create_draft(normalized).valid


def test_strip_malformed_previous_field_refs_removes_non_authorable_noise() -> None:
    arguments = {
        "flow_name": "Robust rapport",
        "plan_rationale": "Skapa rapport.",
        "steps": [
            {
                "name": "Extrahera",
                "instructions": "Extrahera.",
                "input_source": "flow_input",
                "uses_previous_fields": "risker",
            },
            {
                "name": "Skriv",
                "instructions": "Skriv.",
                "input_source": "previous_step",
                "uses_previous_fields": [
                    {"from_step": 0, "field_path": "risk"},
                    {"from_step": 1, "field_path": "risk"},
                    {"from_step": 1, "field_path": "risk"},
                    {"from_step": 1, "field_path": "  "},
                    {"from_step": 1, "field_path": "risk", "label": " Risk "},
                ],
            },
        ],
    }

    cleaned = strip_malformed_previous_field_refs(arguments)

    assert "uses_previous_fields" not in cleaned["steps"][0]
    assert cleaned["steps"][1]["uses_previous_fields"] == [
        {"from_step": 1, "field_path": "risk"},
    ]
