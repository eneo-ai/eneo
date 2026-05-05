from __future__ import annotations

from intric.flows.ai_builder.ai_builder_create_feedback import (
    format_create_quality_feedback,
    format_create_validation_feedback,
)
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult


def test_format_create_validation_feedback_adds_first_step_source_rule() -> None:
    validation = SpecValidationResult()
    validation.add_error(
        step_ref="step_a",
        code="first_step_invalid_source",
        message="Step 1 must use flow_input.",
    )

    feedback = format_create_validation_feedback(validation)

    assert "Create draft validation failed" in feedback
    assert "runtime entry step" in feedback
    assert "committed architecture" in feedback


def test_format_create_validation_feedback_adds_json_all_previous_steps_rule() -> None:
    validation = SpecValidationResult()
    validation.add_error(
        step_ref="step_b",
        code="json_incompatible_with_all_previous_steps",
        message=(
            "input_type 'json' is incompatible with input_source 'all_previous_steps'."
        ),
    )

    feedback = format_create_validation_feedback(validation)

    assert "Create draft validation failed" in feedback
    assert "Outline-flow repair rules" in feedback
    assert "semantic extraction and synthesis steps" in feedback
    assert "server-owned fan-in" in feedback


def test_format_create_quality_feedback_adds_terminal_artifact_rule() -> None:
    feedback = format_create_quality_feedback(
        "Du har valt DOCX som slutartefakt men sista steget producerar inte DOCX."
    )

    assert feedback is not None
    assert "Outline-flow quality repair rules" in feedback
    assert "final step output_type to 'docx'" in feedback


def test_format_create_quality_feedback_does_not_redirect_input_source_authoring() -> (
    None
):
    feedback = format_create_quality_feedback(
        "Det sista steget har "
        '`input_source="all_previous_steps"` trots att tidigare steg producerar JSON.'
    )

    assert feedback is not None
    assert "Outline-flow quality repair rules" not in feedback
    assert "let the backend compile the dataflow" not in feedback
    assert "do not author input_source" not in feedback.casefold()
