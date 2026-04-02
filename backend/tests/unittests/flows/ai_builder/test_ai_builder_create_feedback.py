from __future__ import annotations

from intric.flows.ai_builder.ai_builder_create_feedback import (
    format_create_argument_error,
    format_create_quality_feedback,
    format_create_validation_feedback,
)
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult


def test_format_create_argument_error_guides_output_fields_depth_repairs() -> None:
    feedback = format_create_argument_error(
        ValueError(
            "1 validation error for FlowCreateDraft\n"
            "steps.1\n"
            "  Structured field nesting depth cannot exceed 3."
        )
    )

    assert "Invalid create_flow arguments" in feedback
    assert "output_fields" in feedback
    assert "max 3 levels" in feedback


def test_format_create_validation_feedback_adds_first_step_source_rule() -> None:
    validation = SpecValidationResult()
    validation.add_error(
        step_ref="step_a",
        code="first_step_invalid_source",
        message="Step 1 must use flow_input.",
    )

    feedback = format_create_validation_feedback(validation)

    assert "Create draft validation failed" in feedback
    assert "steps[0].input_source" in feedback
    assert "flow_input" in feedback


def test_format_create_quality_feedback_adds_terminal_artifact_and_aggregation_rules() -> None:
    feedback = format_create_quality_feedback(
        "Du har valt DOCX som slutartefakt men sista steget producerar inte DOCX. "
        "När flera dokument ska sammanställas bör du använda `input_source=\"all_previous_steps\"`."
    )

    assert feedback is not None
    assert "Create-flow quality repair rules" in feedback
    assert "final step output_type to 'docx'" in feedback
    assert "input_source='all_previous_steps'" in feedback
