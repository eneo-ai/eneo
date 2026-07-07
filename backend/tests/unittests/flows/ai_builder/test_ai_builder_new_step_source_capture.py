from __future__ import annotations

import logging

from eneo.flows.ai_builder.ai_builder_new_step_compiler import (
    SourceCaptureField,
    compile_new_step_draft,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import NewStepDraft
from eneo.flows.flow_authoring_spec import InputType, OutputType

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
