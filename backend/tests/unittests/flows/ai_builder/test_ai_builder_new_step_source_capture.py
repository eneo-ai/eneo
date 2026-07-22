from __future__ import annotations

import logging

from eneo.flows.ai_builder.ai_builder_new_step_compiler import (
    _source_ref_payloads_if_valid,
    compile_input_reference_instruction_hint,
    compile_new_step_draft,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    PreviousFieldRef,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_source_reader_contracts import SourceCaptureField
from eneo.flows.flow_authoring_spec import InputSource, InputType, OutputType
from eneo.flows.input_binding_contract_rules import SourceRefBinding

_LOGGER_NAME = "eneo.flows.ai_builder.ai_builder_new_step_compiler"


def _compile_source_capture_instructions(
    source_capture_fields: tuple[SourceCaptureField, ...],
) -> str:
    step = compile_new_step_draft(
        step_draft=NewStepDraft(
            name="Extract source",
            instructions="Read the source material.",
            input_type=InputType.DOCUMENT,
            output_type=OutputType.JSON,
        ),
        plan_step_ref="step_a",
        prior_steps=[],
        source_capture_fields=source_capture_fields,
    )
    return step.assistant_spec.instructions


def test_source_capture_guidance_logs_when_field_count_cap_binds(caplog) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER_NAME)

    instructions = _compile_source_capture_instructions(
        tuple(SourceCaptureField(f"field_{index}") for index in range(9))
    )

    record = next(
        item
        for item in caplog.records
        if item.message == "ai_builder_source_capture_guidance_cap_bound"
    )
    assert record.cap_reason == "field_count"
    assert record.field_cap == 8
    assert record.eligible_field_count == 9
    assert record.rendered_field_count == 8
    assert "- field_7" in instructions
    assert "- field_8" not in instructions


def test_source_capture_guidance_logs_when_block_char_cap_binds(caplog) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER_NAME)

    instructions = _compile_source_capture_instructions(
        (SourceCaptureField(f"field_{'x' * 900}"),)
    )

    record = next(
        item
        for item in caplog.records
        if item.message == "ai_builder_source_capture_guidance_cap_bound"
    )
    assert record.cap_reason == "block_chars"
    assert record.block_char_cap == 900
    assert record.eligible_field_count == 1
    assert record.rendered_field_count == 0
    assert instructions == "Read the source material."


def test_source_capture_guidance_logs_when_description_truncates(caplog) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER_NAME)

    instructions = _compile_source_capture_instructions(
        (SourceCaptureField("summary", "a" * 120),)
    )

    record = next(
        item
        for item in caplog.records
        if item.message == "ai_builder_source_capture_description_truncated"
    )
    assert record.field_names == ["summary"]
    assert record.description_char_cap == 96
    assert record.truncated_field_count == 1
    assert "- summary: " in instructions
    assert "..." in instructions
    assert "a" * 120 not in instructions


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


def test_invalid_source_ref_payload_fallback_logs(caplog) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER_NAME)

    assert (
        _source_ref_payloads_if_valid(
            [
                SourceRefBinding(
                    step_ref="step_a",
                    output="text",
                    field_path=("summary",),
                )
            ]
        )
        is None
    )
    record = next(
        item
        for item in caplog.records
        if item.message == "ai_builder_source_refs_degraded_to_question_binding"
    )
    assert record.source_ref_count == 1
    assert record.source_ref_expressions == ["{{ step_a.output.text.summary }}"]
    assert "field_path" in record.error
