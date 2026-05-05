from __future__ import annotations

from intric.flows.ai_builder.ai_builder_plan_store import format_revision_feedback
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult


def format_create_validation_feedback(validation: SpecValidationResult) -> str:
    base_feedback = format_revision_feedback(
        "Create draft validation failed",
        [error.message for error in validation.errors],
    )
    codes = {error.code for error in validation.errors}
    repair_rules: list[str] = []
    if "first_step_invalid_source" in codes:
        repair_rules.append(
            "Keep the first outline step as the semantic runtime entry step. Do not try to set low-level input_source or runtime upload fields; the backend derives them from the committed architecture."
        )
    if "multiple_flow_input" in codes:
        repair_rules.append(
            "Describe a single first outline step for the runtime material. Later outline steps should describe semantic work only; the backend derives step-to-step wiring."
        )
    if "media_source_mismatch" in codes:
        repair_rules.append(
            "Keep the outline focused on the user's semantic task; the backend already knows the uploaded media type from the committed architecture."
        )
    if "json_incompatible_with_all_previous_steps" in codes:
        repair_rules.append(
            "Describe the semantic extraction and synthesis steps only. The backend will choose previous-step JSON chaining or server-owned fan-in where the committed architecture requires it."
        )
    if not repair_rules:
        return base_feedback
    return f"{base_feedback}\nOutline-flow repair rules:\n- " + "\n- ".join(
        repair_rules
    )


def format_create_quality_feedback(feedback: str | None) -> str | None:
    if feedback is None:
        return None

    normalized_feedback = feedback.casefold()
    repair_rules: list[str] = []
    if (
        "valt docx som slutartefakt" in normalized_feedback
        and "producerar inte docx" in normalized_feedback
    ):
        repair_rules.append(
            "Set the final step output_type to 'docx' so the last step matches the requested final artifact."
        )
    if (
        "valt pdf som slutartefakt" in normalized_feedback
        and "producerar inte pdf" in normalized_feedback
    ):
        repair_rules.append(
            "Set the final step output_type to 'pdf' so the last step matches the requested final artifact."
        )
    if not repair_rules:
        return feedback
    return f"{feedback}\n\nOutline-flow quality repair rules:\n- " + "\n- ".join(
        repair_rules
    )
