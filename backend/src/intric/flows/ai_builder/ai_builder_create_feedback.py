from __future__ import annotations

import re

from intric.flows.ai_builder.ai_builder_plan_store import format_revision_feedback
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult

_STRUCTURED_FIELD_DEPTH_ERROR_RE = re.compile(
    r"Structured field nesting depth cannot exceed (\d+)"
)


def format_create_argument_error(error: Exception) -> str:
    raw_message = str(error)
    depth_match = _STRUCTURED_FIELD_DEPTH_ERROR_RE.search(raw_message)
    if depth_match is not None:
        max_depth = depth_match.group(1)
        return (
            f"Invalid create_flow arguments: {raw_message}\n"
            "Flatten output_fields and keep only realistic structured fields. "
            f"output_fields may nest at max {max_depth} levels: top-level fields, child fields, "
            "and one grandchild level only."
        )
    return f"Invalid create_flow arguments: {raw_message}"


def format_create_validation_feedback(validation: SpecValidationResult) -> str:
    base_feedback = format_revision_feedback(
        "Create draft validation failed",
        [error.message for error in validation.errors],
    )
    codes = {error.code for error in validation.errors}
    repair_rules: list[str] = []
    if "first_step_invalid_source" in codes:
        repair_rules.append(
            "Set steps[0].input_source to 'flow_input'. The first create step is always the runtime entry step. Only later steps may use previous_step or all_previous_steps."
        )
    if "multiple_flow_input" in codes:
        repair_rules.append(
            "Only later steps may use previous_step or all_previous_steps. Keep flow_input only on steps[0]."
        )
    if "media_source_mismatch" in codes:
        repair_rules.append(
            "audio/document/file inputs require input_source='flow_input' on the entry step."
        )
    if "json_incompatible_with_all_previous_steps" in codes:
        repair_rules.append(
            "input_type='json' cannot be combined with input_source='all_previous_steps' "
            "because concatenated text from multiple steps is not valid JSON. "
            "Pick one: (a) set input_source='previous_step' and reference specific fields "
            "via uses_previous_fields when the step consumes structured JSON from the "
            "immediately preceding step; or (b) set input_type='text' when the step "
            "should summarize or synthesize concatenated text from all earlier steps."
        )
    if not repair_rules:
        return base_feedback
    return f"{base_feedback}\nCreate-flow repair rules:\n- " + "\n- ".join(repair_rules)


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
    if (
        '`input_source="all_previous_steps"`' in feedback
        or '`input_source=\\"all_previous_steps\\"`' in feedback
    ):
        repair_rules.append(
            "When several uploaded documents must be combined into one shared analysis or report, add an aggregation step with input_source='all_previous_steps' before the final synthesis step."
        )
    if not repair_rules:
        return feedback
    return f"{feedback}\n\nCreate-flow quality repair rules:\n- " + "\n- ".join(
        repair_rules
    )
