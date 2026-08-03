from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_new_step_compiler import (
    compile_input_reference_instruction_hint,
    compile_new_step_draft,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    PreviousFieldRef,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import (
    SourceCaptureField,
)
from eneo.flows.flow_authoring_spec import InputSource, InputType, OutputType


def _compile_source_capture_instructions(
    source_capture_fields: tuple[SourceCaptureField, ...],
    *,
    instructions: str = "Read the source material.",
    ui_language: str | None = None,
) -> str:
    step = compile_new_step_draft(
        step_draft=NewStepDraft(
            name="Extract source",
            instructions=instructions,
            input_type=InputType.DOCUMENT,
            output_type=OutputType.JSON,
        ),
        plan_step_ref="step_a",
        prior_steps=[],
        source_capture_fields=source_capture_fields,
        ui_language=ui_language,
    )
    return step.assistant_spec.instructions


def test_source_capture_guidance_renders_every_admitted_field_in_order() -> None:
    authored_description = f"{'a' * 500}\n{'b' * 500}"
    complete_description = " ".join(authored_description.split())
    source_capture_fields = tuple(
        SourceCaptureField(
            f"field_{index}",
            authored_description if index == 8 else None,
        )
        for index in range(9)
    )

    instructions = _compile_source_capture_instructions(source_capture_fields)

    field_lines = [f"- field_{index}" for index in range(8)]
    field_lines.append(f"- field_8: {complete_description}")
    expected_guidance = "\n".join(
        [
            "Bevara följande uppgifter eftersom senare steg behöver dem:",
            *field_lines,
            "Om en uppgift saknas i källmaterialet, skriv att den inte framgår "
            "istället för att utelämna den.",
        ]
    )
    assert instructions == f"Read the source material.\n\n{expected_guidance}"


def test_source_capture_guidance_keeps_field_named_inside_instructions() -> None:
    instructions = _compile_source_capture_instructions(
        (SourceCaptureField("id", "Stable source identifier."),),
        instructions="Validate the candidate record.",
        ui_language="en",
    )

    assert instructions == (
        "Validate the candidate record.\n\n"
        "Preserve these facts because later steps need them:\n"
        "- id: Stable source identifier.\n"
        "If a fact is missing from the source material, state that it is not "
        "present instead of omitting it."
    )


def test_output_field_guidance_keeps_field_named_in_instructions() -> None:
    step = compile_new_step_draft(
        step_draft=NewStepDraft(
            name="Extract metadata",
            instructions="Extract the title from the document.",
            input_type=InputType.DOCUMENT,
            output_type=OutputType.JSON,
            output_fields=[
                StructuredFieldDraft(
                    name="title",
                    field_type="string",
                    description="Document title exactly as written.",
                )
            ],
        ),
        plan_step_ref="step_a",
        prior_steps=[],
    )

    instructions = step.assistant_spec.instructions
    assert "Required JSON fields:" in instructions
    assert "- title: Document title exactly as written." in instructions


def test_input_reference_hint_defaults_to_swedish() -> None:
    hint = compile_input_reference_instruction_hint(
        uses_previous_fields=[PreviousFieldRef(from_step=1, field_path="summary")],
        uses_form_fields=["deadline"],
    )

    assert "Beakta särskilt följande strukturerade fält i underlaget:" in hint
    assert "- summary (steg 1: summary)" in hint
    assert "Beakta också följande formulärfält vid analysen:" in hint
    assert "- deadline: {{ flow_input.deadline }}" in hint


def test_input_reference_hint_uses_english_when_requested() -> None:
    hint = compile_input_reference_instruction_hint(
        uses_previous_fields=[PreviousFieldRef(from_step=2, field_path="status")],
        uses_form_fields=["owner"],
        ui_language="en",
    )

    assert "Pay particular attention to these structured source fields:" in hint
    assert "- status (step 2: status)" in hint
    assert "Also use these form fields in the analysis:" in hint
    assert "- owner: {{ flow_input.owner }}" in hint


def test_compile_new_step_passes_ui_language_to_input_reference_hint() -> None:
    source_step = compile_new_step_draft(
        step_draft=NewStepDraft(
            name="Decide",
            instructions="Produce a structured decision.",
            output_type=OutputType.JSON,
        ),
        plan_step_ref="step_a",
        prior_steps=[],
    )
    step = compile_new_step_draft(
        step_draft=NewStepDraft(
            name="Summarize all prior work",
            instructions="Write the combined summary.",
            input_source=InputSource.ALL_PREVIOUS_STEPS,
            output_type=OutputType.TEXT,
            uses_previous_fields=[
                PreviousFieldRef(from_step=1, field_path="decision", label="Decision")
            ],
        ),
        plan_step_ref="step_b",
        prior_steps=[source_step],
        ui_language="en",
    )

    assert "Pay particular attention to these structured source fields:" in (
        step.assistant_spec.instructions
    )
    assert "- Decision (step 1: decision)" in step.assistant_spec.instructions
