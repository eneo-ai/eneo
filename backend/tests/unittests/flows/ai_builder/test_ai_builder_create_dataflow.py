from intric.flows.ai_builder.ai_builder_create_compiler import compile_create_draft
from intric.flows.ai_builder.ai_builder_create_dataflow import (
    normalize_create_draft_mechanics,
)
from intric.flows.ai_builder.ai_builder_create_models import FlowCreateDraft
from intric.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft
from intric.flows.ai_builder.ai_builder_output_sections_signals import (
    RequestedOutputSections,
)
from intric.flows.ai_builder.ai_builder_validator import validate_spec
from intric.flows.flow_authoring_spec import FormFieldSpec


def test_create_dataflow_does_not_import_critic_invariants() -> None:
    from pathlib import Path

    import intric.flows.ai_builder.ai_builder_create_dataflow as create_dataflow

    source = Path(create_dataflow.__file__).read_text(encoding="utf-8")

    assert "ai_builder_critic_invariants" not in source


def _field(name: str) -> StructuredFieldDraft:
    return StructuredFieldDraft(
        name=name,
        field_type="string",
        description=f"{name} field.",
    )


def _assert_compiles_to_valid_spec(draft: FlowCreateDraft) -> None:
    assert validate_spec(compile_create_draft(draft)).valid


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

    normalized = normalize_create_draft_mechanics(draft)

    _assert_compiles_to_valid_spec(normalized)
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

    normalized = normalize_create_draft_mechanics(draft)

    _assert_compiles_to_valid_spec(normalized)
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

    _assert_compiles_to_valid_spec(normalized)
    assert normalized.steps[2].input_type == "text"
    assert [
        (ref.from_step, ref.label) for ref in normalized.steps[2].uses_previous_outputs
    ] == [(1, "Källmaterial")]
    assert normalized.steps[3].input_type == "text"
    assert [
        (ref.from_step, ref.label) for ref in normalized.steps[3].uses_previous_outputs
    ] == [(1, "Källmaterial")]
    assert [
        (ref.from_step, ref.label) for ref in normalized.steps[4].uses_previous_outputs
    ] == [(1, "Källmaterial")]
    assert {
        (ref.from_step, ref.field_path)
        for ref in normalized.steps[4].uses_previous_fields
    } >= {
        (2, "transcription_text"),
        (3, "meeting_title"),
        (4, "protocol_sections"),
    }
    assert normalized.steps[5].uses_previous_outputs == []


def test_normalize_create_draft_mechanics_and_critic_share_targeted_underlag_policy() -> (
    None
):
    from intric.flows.ai_builder.ai_builder_create_compiler import compile_create_draft
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

    draft = FlowCreateDraft(
        flow_name="PDF-rapport",
        plan_rationale="Skapar en PDF-rapport med granskningssteg.",
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

    normalized = normalize_create_draft_mechanics(draft)
    composer = normalized.steps[3]

    assert composer.input_source == "previous_step"
    assert {
        (ref.from_step, ref.field_path) for ref in composer.uses_previous_fields
    } >= {
        (2, "background"),
        (3, "findings"),
    }

    spec = compile_create_draft(normalized)
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


def test_normalize_create_draft_mechanics_rewrites_final_assembler_to_section_outputs() -> (
    None
):
    from intric.flows.ai_builder.ai_builder_create_compiler import compile_create_draft

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
    draft = FlowCreateDraft(
        flow_name="Document report",
        plan_rationale="Extract facts, write sections, assemble a document.",
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

    normalized = normalize_create_draft_mechanics(draft)
    assembler = normalized.steps[-2]

    assert assembler.input_source == "previous_step"
    assert [ref.from_step for ref in assembler.uses_previous_outputs] == list(
        range(3, 11)
    )
    assert assembler.uses_previous_fields == []

    spec = compile_create_draft(normalized)
    question = spec.steps[-2].input_bindings["question"]

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


def test_normalize_create_draft_mechanics_preserves_final_assembler_field_refs() -> (
    None
):
    draft = FlowCreateDraft(
        flow_name="Document report with audit facts",
        plan_rationale="Assemble section drafts while preserving explicit audit facts.",
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

    normalized = normalize_create_draft_mechanics(draft)
    assembler = normalized.steps[-2]

    assert [
        (ref.from_step, ref.field_path) for ref in assembler.uses_previous_fields
    ] == [(1, "facts")]
    assert [ref.from_step for ref in assembler.uses_previous_outputs] == [2, 3]


def test_normalize_create_draft_mechanics_rewrites_final_assembler_for_aggregate_intent() -> (
    None
):
    from intric.flows.ai_builder.ai_builder_create_compiler import compile_create_draft
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

    draft = FlowCreateDraft(
        flow_name="Aggregate report",
        plan_rationale="Aggregate multiple prior outputs.",
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
    )

    normalized = normalize_create_draft_mechanics(
        draft,
        aggregation_intent="aggregate",
    )

    assert normalized.steps[-2].input_source == "previous_step"
    assert [ref.from_step for ref in normalized.steps[-2].uses_previous_outputs] == [
        1,
        2,
    ]

    spec = compile_create_draft(normalized)
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


def test_normalize_create_draft_mechanics_keeps_final_assembler_broad_for_compare_intent() -> (
    None
):
    draft = FlowCreateDraft(
        flow_name="Compare report",
        plan_rationale="Compare multiple prior outputs.",
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
    )

    normalized = normalize_create_draft_mechanics(
        draft,
        aggregation_intent="compare",
    )

    assert normalized.steps[-2].input_source == "all_previous_steps"
    assert normalized.steps[-2].uses_previous_outputs == []


def test_normalize_create_draft_mechanics_rewrites_terminal_renderer_all_previous() -> (
    None
):
    draft = FlowCreateDraft(
        flow_name="Document report",
        plan_rationale="Extract facts, compose the body, and render the document.",
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

    normalized = normalize_create_draft_mechanics(draft)
    renderer = normalized.steps[-1]

    assert renderer.input_source == "previous_step"
    assert renderer.uses_previous_fields == []
    assert renderer.uses_previous_outputs == []


def test_normalize_create_draft_mechanics_rewrites_terminal_renderer_for_aggregate_intent() -> (
    None
):
    draft = FlowCreateDraft(
        flow_name="Aggregate report",
        plan_rationale="Aggregate prior outputs into one PDF.",
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
    )

    normalized = normalize_create_draft_mechanics(
        draft,
        aggregation_intent="aggregate",
    )

    assert normalized.steps[-1].input_source == "previous_step"


def test_normalize_create_draft_mechanics_keeps_terminal_renderer_without_text_composer() -> (
    None
):
    draft = FlowCreateDraft(
        flow_name="Structured artifact",
        plan_rationale="Extract structured data before rendering.",
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

    normalized = normalize_create_draft_mechanics(draft)

    assert normalized.steps[-1].input_source == "all_previous_steps"


def test_normalize_create_draft_mechanics_rewrites_assembler_before_terminal_renderer() -> (
    None
):
    draft = FlowCreateDraft(
        flow_name="Document report",
        plan_rationale="Write sections, assemble them, and render the report.",
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

    normalized = normalize_create_draft_mechanics(draft)

    assert normalized.steps[-2].input_source == "previous_step"
    assert [ref.from_step for ref in normalized.steps[-2].uses_previous_outputs] == [
        2,
        3,
    ]
    assert normalized.steps[-1].input_source == "previous_step"
    assert normalized.steps[-1].uses_previous_outputs == []


def test_normalize_create_draft_mechanics_rewrites_assembler_before_review_and_renderer() -> (
    None
):
    draft = FlowCreateDraft(
        flow_name="Document report with final review",
        plan_rationale="Write sections, assemble them, review, and render.",
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

    normalized = normalize_create_draft_mechanics(draft)

    assembler = normalized.steps[3]
    assert assembler.input_source == "previous_step"
    assert [ref.from_step for ref in assembler.uses_previous_outputs] == [2, 3]
    assert normalized.steps[4].input_source == "previous_step"
    assert normalized.steps[5].input_source == "previous_step"


def test_normalize_create_draft_mechanics_keeps_non_source_text_step_label() -> None:
    draft = FlowCreateDraft(
        flow_name="Textbaserad sammanställning",
        plan_rationale="Skriv rapport från text och strukturerade fält.",
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

    normalized = normalize_create_draft_mechanics(draft)

    assert [
        (ref.from_step, ref.label) for ref in normalized.steps[3].uses_previous_outputs
    ] == [(1, "Samla anteckningar")]


def test_normalize_create_draft_mechanics_prunes_unknown_form_field_refs() -> None:
    draft = FlowCreateDraft(
        flow_name="Robust formulärflöde",
        plan_rationale="Använd runtime metadata om den finns.",
        form_fields=[
            FormFieldSpec(
                name="case_id",
                label="Case ID",
                type="text",
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

    normalized = normalize_create_draft_mechanics(draft)

    _assert_compiles_to_valid_spec(normalized)
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

    normalized = normalize_create_draft_mechanics(draft)
    compiled = compile_create_draft(normalized)
    runtime_input = compiled.steps[0].input_config["runtime_input"]

    assert normalized.steps[0].input_source == "flow_input"
    assert runtime_input["enabled"] is True
    assert runtime_input["input_format"] == "document"
    assert runtime_input["required"] is True
    assert normalized.steps[1].input_source == "previous_step"
    assert normalized.steps[1].input_type == "json"
    assert normalized.steps[1].document_delivery_mode == "not_applicable"
    assert normalized.steps[2].input_type == "text"
    assert normalized.steps[2].citations_requested is False
    _assert_compiles_to_valid_spec(normalized)
