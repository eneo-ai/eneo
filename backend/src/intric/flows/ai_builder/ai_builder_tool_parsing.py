from __future__ import annotations

from typing import Any, cast

from pydantic import ValidationError

from intric.flows.ai_builder.ai_builder_create_models import FlowCreateDraft
from intric.flows.ai_builder.ai_builder_framework_policy import (
    is_supported_structured_question_id,
)

_CREATE_STEP_REQUIRED_FIELDS = frozenset({"name", "instructions", "input_source"})
_STRUCTURED_FIELD_REQUIRED_FIELDS = frozenset(
    {"name", "field_type", "description", "required"}
)
_CREATE_FORM_FIELD_REQUIRED_FIELDS = frozenset(
    {"variable_name", "label", "field_type", "required"}
)


class RecoverableToolPayloadError(ValueError):
    """Raised when tool payload structure is malformed but retryable.

    This captures cases where the model produced commentary, placeholders, or
    quoted fragments where an object/list is required. The parser stays strict
    and does not invent semantic content, but the repair loop can use the typed
    error to issue stronger structural retry guidance.
    """


def parse_create_flow_arguments(arguments: dict[str, Any]) -> FlowCreateDraft:
    """Parse and validate the new create-mode IR payload."""
    arguments = _unwrap_spec_payload(arguments)
    cleaned = {key: value for key, value in arguments.items() if key != "reasoning"}
    cleaned = _normalize_misplaced_create_step_entries(cleaned)
    try:
        return FlowCreateDraft.model_validate(cleaned)
    except ValidationError as error:
        actionable_error = _describe_create_draft_validation_error(error)
        if actionable_error is not None:
            raise RecoverableToolPayloadError(actionable_error) from error
        raise


def extract_assumptions(arguments: dict[str, Any]) -> list[str]:
    raw = arguments.get("assumptions")
    if isinstance(raw, list):
        return [item for item in cast(list[Any], raw) if isinstance(item, str)]
    return []


def extract_reasoning(arguments: dict[str, Any]) -> str | None:
    raw = arguments.get("reasoning")
    return str(raw) if isinstance(raw, str) and raw else None


def extract_plan_rationale(arguments: dict[str, Any]) -> str | None:
    raw = arguments.get("plan_rationale")
    return str(raw) if isinstance(raw, str) and raw else None


def parse_structured_question(arguments: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate ask_structured_question arguments."""
    question_id = arguments.get("question_id")
    if not isinstance(question_id, str) or not question_id.strip():
        raise ValueError("question_id must be a non-empty string")
    if not is_supported_structured_question_id(question_id):
        raise ValueError(
            "question_id must be one of the supported canonical AI Builder ids"
        )

    question = arguments.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")

    options = arguments.get("options")
    if not isinstance(options, list):
        raise ValueError("options must be a list with at least 2 items")
    options_list = cast(list[Any], options)
    if len(options_list) < 2:
        raise ValueError("options must be a list with at least 2 items")

    cleaned_options: list[dict[str, Any]] = []
    for opt in options_list:
        if not isinstance(opt, dict):
            raise ValueError("each option must have a string 'label'")
        option_dict = cast(dict[str, Any], opt)
        if not isinstance(option_dict.get("label"), str):
            raise ValueError("each option must have a string 'label'")
        cleaned_options.append(
            {
                "id": option_dict.get("id"),
                "label": option_dict["label"],
                "value": option_dict.get("value"),
                "description": option_dict.get("description"),
            }
        )

    selection_mode = arguments.get("selection_mode", "single")
    if selection_mode not in {"single", "multi"}:
        raise ValueError("selection_mode must be 'single' or 'multi'")

    allow_custom = arguments.get("allow_custom", True)
    if not isinstance(allow_custom, bool):
        raise ValueError("allow_custom must be boolean")

    return {
        "question_id": question_id.strip(),
        "question": question.strip(),
        "options": cleaned_options,
        "selection_mode": selection_mode,
        "allow_custom": allow_custom,
    }


def parse_confirm_requirements(arguments: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate confirm_requirements arguments."""
    summary = arguments.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("summary must be a non-empty string")

    key_decisions = arguments.get("key_decisions")
    if not isinstance(key_decisions, list):
        raise ValueError("key_decisions must be a list with at least 1 item")
    decisions_list = cast(list[Any], key_decisions)
    if len(decisions_list) < 1:
        raise ValueError("key_decisions must be a list with at least 1 item")

    cleaned_decisions: list[dict[str, str]] = []
    for decision in decisions_list:
        if not isinstance(decision, dict):
            raise ValueError("each key_decision must be an object")
        decision_dict = cast(dict[str, Any], decision)
        topic = decision_dict.get("topic")
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("each key_decision must have a non-empty string 'topic'")
        dec_value = decision_dict.get("decision")
        if not isinstance(dec_value, str) or not dec_value.strip():
            raise ValueError(
                "each key_decision must have a non-empty string 'decision'"
            )
        cleaned_decisions.append(
            {
                "topic": topic.strip(),
                "decision": dec_value.strip(),
            }
        )

    input_description = arguments.get("input_description")
    if not isinstance(input_description, str) or not input_description.strip():
        raise ValueError("input_description must be a non-empty string")

    output_description = arguments.get("output_description")
    if not isinstance(output_description, str) or not output_description.strip():
        raise ValueError("output_description must be a non-empty string")

    raw_notes = arguments.get("manual_setup_notes")
    manual_setup_notes: list[str] = []
    if isinstance(raw_notes, list):
        manual_setup_notes = [
            note for note in cast(list[Any], raw_notes) if isinstance(note, str)
        ]

    raw_assumptions = arguments.get("assumptions")
    assumptions: list[str] = []
    if isinstance(raw_assumptions, list):
        assumptions = [
            str(item).strip()
            for item in cast(list[Any], raw_assumptions)
            if isinstance(item, str) and str(item).strip()
        ]

    return {
        "summary": summary.strip(),
        "key_decisions": cleaned_decisions,
        "input_description": input_description.strip(),
        "output_description": output_description.strip(),
        "assumptions": assumptions,
        "manual_setup_notes": manual_setup_notes,
    }


def _unwrap_spec_payload(arguments: dict[str, Any]) -> dict[str, Any]:
    """Accept common nested wrapper shapes some models use around flow drafts."""
    for key in ("spec", "draft", "flow"):
        candidate = arguments.get(key)
        if (
            isinstance(candidate, dict)
            and "flow_name" in candidate
            and ("steps" in candidate or "form_fields" in candidate)
        ):
            return cast(dict[str, Any], candidate)
    return arguments


def _describe_create_draft_validation_error(error: ValidationError) -> str | None:
    messages: list[str] = []
    handled_step_indexes: set[int] = set()
    for item in error.errors():
        loc = item["loc"]
        path = list(loc)
        if len(path) >= 2 and path[0] == "steps" and isinstance(path[1], int):
            step_index = path[1]
            if step_index in handled_step_indexes:
                continue
            payload = item.get("input")
            if isinstance(payload, dict):
                misplaced_message = _describe_misplaced_create_step_payload(
                    step_index=step_index,
                    payload=cast(dict[str, Any], payload),
                )
                if misplaced_message is not None:
                    messages.append(misplaced_message)
                    handled_step_indexes.add(step_index)
    if messages:
        return "\n".join(messages)
    return None


def _describe_misplaced_create_step_payload(
    *,
    step_index: int,
    payload: dict[str, Any],
) -> str | None:
    payload_kind = _classify_misplaced_create_step_payload(payload)
    if payload_kind == "structured_field":
        return (
            f"steps[{step_index}] looks like a structured output field, not a step. "
            "Move this object into output_fields on the JSON-producing parent step instead of steps[]. "
            "Every steps[] item must be a full create step object with at least name, instructions, input_source, and output_type."
        )
    if payload_kind == "form_field":
        return (
            f"steps[{step_index}] looks like a form field, not a step. "
            "Move this object into form_fields instead of steps[]. "
            "Every steps[] item must be a full create step object with at least name, instructions, input_source, and output_type."
        )
    return None


def _classify_misplaced_create_step_payload(
    payload: dict[str, Any],
) -> str | None:
    payload_keys = set(payload)
    missing_step_fields = _CREATE_STEP_REQUIRED_FIELDS - payload_keys
    if not missing_step_fields:
        return None
    if _STRUCTURED_FIELD_REQUIRED_FIELDS.issubset(payload_keys):
        return "structured_field"
    if _CREATE_FORM_FIELD_REQUIRED_FIELDS.issubset(payload_keys):
        return "form_field"
    return None


def _normalize_misplaced_create_step_entries(
    arguments: dict[str, Any],
) -> dict[str, Any]:
    raw_steps = arguments.get("steps")
    if not isinstance(raw_steps, list):
        return arguments

    changed = False
    normalized_steps: list[object] = []
    for raw_step in cast(list[object], raw_steps):
        if not isinstance(raw_step, dict):
            normalized_steps.append(raw_step)
            continue

        raw_step_dict = cast(dict[str, Any], raw_step)
        if _classify_misplaced_create_step_payload(raw_step_dict) == "structured_field":
            parent_step = _latest_json_parent_step(normalized_steps)
            if parent_step is not None:
                output_fields = parent_step.setdefault("output_fields", [])
                if isinstance(output_fields, list):
                    cast(list[object], output_fields).append(dict(raw_step_dict))
                    changed = True
                    continue
        normalized_steps.append(dict(raw_step_dict))

    if not changed:
        return arguments

    normalized_arguments = dict(arguments)
    normalized_arguments["steps"] = normalized_steps
    return normalized_arguments


def _latest_json_parent_step(steps: list[object]) -> dict[str, Any] | None:
    for step in reversed(steps):
        if not isinstance(step, dict):
            continue
        step_dict = cast(dict[str, Any], step)
        if step_dict.get("output_type") == "json":
            return step_dict
    return None
