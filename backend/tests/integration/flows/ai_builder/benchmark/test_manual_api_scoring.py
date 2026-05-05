from __future__ import annotations

from dataclasses import replace

from intric.flows.ai_builder.ai_builder_domain_models import FlowDraftSpecCore
from tests.integration.flows.ai_builder.benchmark.cases import manual_api_eval_cases
from tests.integration.flows.ai_builder.benchmark.manual_api_scoring import (
    score_plan_mechanics,
)


def _case(case_id: str):
    return next(case for case in manual_api_eval_cases() if case.case_id == case_id)


def _spec(
    *,
    steps: list[dict[str, object]],
    form_fields: list[dict[str, object]] | None = None,
) -> FlowDraftSpecCore:
    return FlowDraftSpecCore.model_validate(
        {
            "flow_name": "Mötesprotokoll från ljud till Word",
            "flow_description": "Test fixture.",
            "steps": [
                {
                    "assistant_spec": {"instructions": "Do the step."},
                    **step,
                }
                for step in steps
            ],
            "form_fields": form_fields,
        }
    )


def _audio_transcription_step() -> dict[str, object]:
    return {
        "plan_step_ref": "step_a",
        "name": "Transkribera ljud",
        "input_source": "flow_input",
        "input_type": "audio",
        "output_type": "text",
        "output_mode": "transcribe_only",
    }


def test_reported_bad_underlag_shape_fails_deterministic_scoring() -> None:
    spec = _spec(
        steps=[
            _audio_transcription_step(),
            {
                "plan_step_ref": "step_b",
                "name": "Strukturera transkription",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_mode": "pass_through",
            },
            {
                "plan_step_ref": "step_c",
                "name": "Identifiera metadata",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "json",
                "output_mode": "pass_through",
            },
            {
                "plan_step_ref": "step_d",
                "name": "Skapa DOCX",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "docx",
                "output_mode": "pass_through",
            },
        ],
        form_fields=[
            {
                "name": "language",
                "type": "text",
                "label": "Language",
                "required": False,
            },
            {
                "name": "timestamps",
                "type": "text",
                "label": "Timestamps",
                "required": False,
            },
        ],
    )

    score = score_plan_mechanics(
        spec=spec,
        corpus_case=_case("advanced_audio_meeting_docx_sv"),
    )

    assert score.derived.uses_underlag_till_text_correctly is False
    assert score.derived.uses_runtime_input_fields_correctly is False
    assert "uses_underlag_till_text_correctly" in score.typed_failures
    assert "uses_runtime_input_fields_correctly" in score.typed_failures


def test_post_fix_underlag_shape_passes_deterministic_scoring() -> None:
    spec = _spec(
        steps=[
            _audio_transcription_step(),
            {
                "plan_step_ref": "step_b",
                "name": "Strukturera transkription",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_mode": "pass_through",
            },
            {
                "plan_step_ref": "step_c",
                "name": "Identifiera metadata",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_mode": "pass_through",
                "input_bindings": {
                    "question": (
                        "{{ step_b.output.structured }}\n\n"
                        "Källmaterial: {{ step_a.output.text }}"
                    )
                },
            },
            {
                "plan_step_ref": "step_d",
                "name": "Skapa mötesprotokoll",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "docx",
                "output_mode": "pass_through",
                "input_bindings": {
                    "question": (
                        "{{ step_c.output.structured }}\n\n"
                        "Källmaterial: {{ step_a.output.text }}"
                    )
                },
            },
        ],
    )

    score = score_plan_mechanics(
        spec=spec,
        corpus_case=_case("advanced_audio_meeting_docx_sv"),
    )

    assert score.derived.uses_underlag_till_text_correctly is True
    assert score.derived.uses_runtime_input_fields_correctly is True
    assert "uses_underlag_till_text_correctly" not in score.typed_failures
    assert "uses_runtime_input_fields_correctly" not in score.typed_failures


def test_document_source_text_boundary_is_scored_like_audio_source_material() -> None:
    spec = _spec(
        steps=[
            {
                "plan_step_ref": "step_a",
                "name": "Läs underlag",
                "input_source": "flow_input",
                "input_type": "document",
                "output_type": "text",
                "output_mode": "pass_through",
            },
            {
                "plan_step_ref": "step_b",
                "name": "Extrahera struktur",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_mode": "pass_through",
            },
            {
                "plan_step_ref": "step_c",
                "name": "Skriv sammanställning",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "docx",
                "output_mode": "pass_through",
                "input_bindings": {
                    "question": (
                        "{{ step_b.output.structured }}\n\n"
                        "Källmaterial: {{ step_a.output.text }}"
                    )
                },
            },
        ],
    )

    score = score_plan_mechanics(
        spec=spec,
        corpus_case=_case("vague_multi_file_docx_sv"),
    )

    assert score.derived.uses_underlag_till_text_correctly is True
    assert "uses_underlag_till_text_correctly" not in score.typed_failures


def test_text_terminal_missing_source_material_fails_deterministic_scoring() -> None:
    spec = _spec(
        steps=[
            _audio_transcription_step(),
            {
                "plan_step_ref": "step_b",
                "name": "Extract decisions",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "json",
                "output_mode": "pass_through",
            },
            {
                "plan_step_ref": "step_c",
                "name": "Write final report",
                "input_source": "previous_step",
                "input_type": "json",
                "output_type": "text",
                "output_mode": "pass_through",
                "input_bindings": {"question": "{{ step_b.output.structured }}"},
            },
        ],
    )

    score = score_plan_mechanics(
        spec=spec,
        corpus_case=_case("vague_audio_docx_sv"),
    )

    assert score.derived.uses_underlag_till_text_correctly is False
    assert "uses_underlag_till_text_correctly" in score.typed_failures


def test_expected_runtime_metadata_fields_are_allowed() -> None:
    corpus_case = replace(
        _case("vague_audio_docx_sv"),
        expected_secondary_runtime_field_names=frozenset({"audience"}),
    )
    spec = _spec(
        steps=[
            _audio_transcription_step(),
            {
                "plan_step_ref": "step_b",
                "name": "Skapa DOCX",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "docx",
                "output_mode": "pass_through",
            },
        ],
        form_fields=[
            {
                "name": "audience",
                "type": "text",
                "label": "Audience",
                "required": False,
            }
        ],
    )

    score = score_plan_mechanics(spec=spec, corpus_case=corpus_case)

    assert score.derived.uses_runtime_input_fields_correctly is True
    assert "uses_runtime_input_fields_correctly" not in score.typed_failures


def test_audio_transcript_form_field_is_scored_as_duplicate_primary_input() -> None:
    spec = _spec(
        steps=[
            _audio_transcription_step(),
            {
                "plan_step_ref": "step_b",
                "name": "Skapa DOCX",
                "input_source": "previous_step",
                "input_type": "text",
                "output_type": "docx",
                "output_mode": "pass_through",
            },
        ],
        form_fields=[
            {
                "name": "transcript",
                "type": "text",
                "label": "Transcript",
                "required": False,
            }
        ],
    )

    score = score_plan_mechanics(
        spec=spec,
        corpus_case=_case("vague_audio_docx_sv"),
    )

    assert score.derived.uses_runtime_input_fields_correctly is False
    assert "uses_runtime_input_fields_correctly" in score.typed_failures
